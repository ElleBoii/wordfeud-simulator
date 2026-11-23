"""Kör en Monte Carlo-simulering, i samma process eller fördelat på en processpool.

Varje uppgift är en rollout (kandidat, iteration). Eftersom en rollout bara
beror på (kontext, kandidat, iteration) blir resultatet detsamma oavsett hur
uppgifterna fördelas, så länge seed är fast.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from .dictionary import Dictionary
from .evaluation import LeaveModel, WinModel
from .movegen import Move
from .sim import CandidateStats, SimContext, prune, rollout, sort_key

# --- arbetsprocesser -------------------------------------------------------------

_W: dict = {"dicts": {}, "jobs": {}, "alphabet": None, "dir": None}


def _worker_init(alphabet: str, dict_dir: str, preload: tuple[str, tuple] | None) -> None:
    _W["alphabet"], _W["dir"] = alphabet, dict_dir
    if preload:
        _worker_dict(*preload)


def _worker_dict(mode: str, stamp: tuple) -> Dictionary:
    hit = _W["dicts"].get(mode)
    if hit is None or hit[0] != stamp:
        d = Dictionary.load(_W["alphabet"], _W["dir"], mode=mode)
        _W["dicts"][mode] = (stamp, d)
        return d
    return hit[1]


def _worker_task(job_key: str, ctx: SimContext, cand: Move, ci: int, it: int,
                 mode: str, stamp: tuple):
    d = _worker_dict(mode, stamp)
    job = _W["jobs"].get(job_key)
    if job is None:
        _W["jobs"] = {}                       # bara senaste jobbet behövs
        job = (ctx.board(), LeaveModel(ctx.leave_cfg, ctx.rules), WinModel(ctx.win_cfg, ctx.rules))
        _W["jobs"][job_key] = job
    board, leave, win = job
    w, m = rollout(ctx, cand, it, d, leave, win, board)
    return ci, it, w, m


def _ping() -> int:
    return os.getpid()


class WorkerPool:
    """Lat processpool med förladdad ordlista i varje arbetare."""

    def __init__(self, alphabet: str, dict_dir: str | Path, workers: int) -> None:
        self.alphabet, self.dir, self.workers = alphabet, str(dict_dir), max(1, workers)
        self._ex: ProcessPoolExecutor | None = None
        self._lock = threading.Lock()

    def executor(self, preload: tuple[str, tuple] | None = None) -> ProcessPoolExecutor:
        with self._lock:
            if self._ex is None:
                self._ex = ProcessPoolExecutor(self.workers, initializer=_worker_init,
                                               initargs=(self.alphabet, self.dir, preload))
            return self._ex

    def warm(self, preload: tuple[str, tuple] | None = None) -> None:
        ex = self.executor(preload)
        for _ in range(self.workers):
            ex.submit(_ping)

    def shutdown(self) -> None:
        with self._lock:
            if self._ex is not None:
                self._ex.shutdown(wait=False, cancel_futures=True)
                self._ex = None


def auto_workers() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


# --- en simulering ----------------------------------------------------------------

@dataclass
class SimSettings:
    iterations: int | None = 500     # iterationer per kandidat (None = tills tidsgränsen)
    max_seconds: float | None = 60.0 # hård tidsgräns (skyddsnät; None = ingen)
    sort: str = "win"
    prune: bool = True
    min_prune: int = 30


@dataclass
class Simulation:
    ctx: SimContext
    candidates: list[tuple[Move, float]]          # (drag, statiskt värde)
    settings: SimSettings
    job_key: str = "job"
    stats: list[CandidateStats] = field(default_factory=list)
    status: str = "pending"                       # running / done / stopped / error
    error: str | None = None
    started: float = 0.0
    finished: float = 0.0
    rollouts: int = 0
    time_limited: bool = False                    # stoppad av den hårda tidsgränsen

    def __post_init__(self) -> None:
        self.stats = [CandidateStats() for _ in self.candidates]
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # --- styrning ---
    def stop(self) -> None:
        self._stop.set()

    def _deadline_hit(self) -> bool:
        lim = self.settings.max_seconds
        if lim is not None and time.perf_counter() - self.started >= lim:
            self.time_limited = True
            return True
        return False

    def _active(self) -> list[int]:
        return [i for i, s in enumerate(self.stats) if not s.pruned]

    def _tasks(self):
        """(kandidat, iteration) i iterationsordning; hoppar över gallrade."""
        it = 0
        while self.candidates:
            if self.settings.iterations is not None and it >= self.settings.iterations:
                return
            for ci in range(len(self.candidates)):
                if not self.stats[ci].pruned:
                    yield ci, it
            it += 1

    def _record(self, ci: int, it: int, w: float, m: float) -> None:
        with self._lock:
            self.stats[ci].add(it, w, m)
            self.rollouts += 1
            if self.settings.prune and self.rollouts % max(1, len(self._active())) == 0:
                prune(self.stats, self.settings.sort, self.settings.min_prune)

    def _done(self) -> bool:
        return (self._stop.is_set() or self._deadline_hit()
                or (len(self.candidates) > 1 and len(self._active()) <= 1))

    def run_inline(self, dictionary: Dictionary) -> None:
        """Kör i den anropande tråden (tester, eller om processpool saknas)."""
        self.status, self.started = "running", time.perf_counter()
        board = self.ctx.board()
        leave = LeaveModel(self.ctx.leave_cfg, self.ctx.rules)
        win = WinModel(self.ctx.win_cfg, self.ctx.rules)
        try:
            for ci, it in self._tasks():
                if self._done():
                    break
                if self.stats[ci].pruned:
                    continue
                w, m = rollout(self.ctx, self.candidates[ci][0], it, dictionary, leave, win, board)
                self._record(ci, it, w, m)
            self._finish()
        except Exception as e:  # noqa: BLE001
            self._fail(e)

    def run_pool(self, pool: WorkerPool, mode: str, stamp: tuple) -> None:
        self.status, self.started = "running", time.perf_counter()
        ex = pool.executor((mode, stamp))
        inflight: set[Future] = set()
        tasks = self._tasks()
        limit = pool.workers * 2
        exhausted = False
        try:
            while True:
                while not exhausted and len(inflight) < limit and not self._done():
                    nxt = next(tasks, None)
                    if nxt is None:
                        exhausted = True
                        break
                    ci, it = nxt
                    inflight.add(ex.submit(_worker_task, self.job_key, self.ctx,
                                           self.candidates[ci][0], ci, it, mode, stamp))
                if not inflight:
                    break
                done, inflight = wait(inflight, timeout=0.25, return_when=FIRST_COMPLETED)
                for f in done:
                    ci, it, w, m = f.result()
                    self._record(ci, it, w, m)
                if self._done():
                    for f in inflight:
                        f.cancel()
                    break
            self._finish()
        except Exception as e:  # noqa: BLE001
            for f in inflight:
                f.cancel()
            self._fail(e)

    def _finish(self) -> None:
        self.finished = time.perf_counter()
        self.status = "stopped" if self._stop.is_set() else "done"

    def _fail(self, e: Exception) -> None:
        self.finished = time.perf_counter()
        self.status, self.error = "error", f"{type(e).__name__}: {e}"

    # --- resultat ---
    def elapsed(self) -> float:
        if not self.started:
            return 0.0
        return (self.finished or time.perf_counter()) - self.started

    def snapshot(self) -> dict:
        with self._lock:
            order = sorted(range(len(self.candidates)),
                           key=lambda i: (self.stats[i].pruned,) + sort_key(self.stats[i], self.settings.sort)
                           + (-self.candidates[i][1],))
            rows = []
            for i in order:
                m, static = self.candidates[i]
                s = self.stats[i]
                rows.append({
                    "index": i, "kind": m.kind, "word": m.word, "row": m.row, "col": m.col,
                    "horizontal": m.horizontal, "score": m.score, "leave": m.leave,
                    "exchanged": m.exchanged, "label": m.describe(), "static": round(static, 1),
                    "placements": [{"row": p.row, "col": p.col, "letter": p.letter, "blank": p.blank}
                                   for p in m.placements],
                    "n": s.n, "pruned": s.pruned,
                    "win": None if s.win is None else round(100 * s.win, 1),
                    "win_se": None if s.win_se is None else round(100 * s.win_se, 1),
                    "margin": None if s.margin is None else round(s.margin, 1),
                    "margin_se": None if s.margin_se is None else round(s.margin_se, 1),
                })
            el = self.elapsed()
            active = [s.n for s in self.stats if not s.pruned]
            return {
                "status": self.status, "error": self.error, "elapsed": round(el, 1),
                "rollouts": self.rollouts, "rate": round(self.rollouts / el, 1) if el > 0 else 0,
                "iterations": min(active) if active else 0,
                "target_iterations": self.settings.iterations,
                "time_limited": self.time_limited,
                "active": len(active), "candidates": rows,
                "settings": {"plies": self.ctx.plies, "opponent_model": self.ctx.opponent_model,
                             "seed": self.ctx.seed, "iterations": self.settings.iterations,
                             "max_seconds": self.settings.max_seconds, "sort": self.settings.sort},
            }
