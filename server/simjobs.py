"""Simuleringsjobb för servern: ett jobb åt gången, körs i en bakgrundstråd.

Innan ett jobb startas kalibreras tidsåtgången i den aktuella ställningen
(wfengine/budget.py) och antalet iterationer begränsas så att simuleringen
ryms inom budgetens maxtid. Ryms inte ens en iteration startas inget jobb.

Inställningarna sparas i settings.json (bredvid games/) så att de är desamma
på datorn och mobilen.
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from wfengine.budget import PLIES_OPTIONS, Calibration, calibrate, moves_left, plan, plan_all
from wfengine.evaluation import LeaveModel
from wfengine.game import Game
from wfengine.rules import Rules
from wfengine.sim import HUMAN, PERFECT, SimContext, select_candidates
from wfengine.simrunner import Simulation, SimSettings, WorkerPool, auto_workers
from wfengine.tiles import unseen_tiles


def plies_label(p: int) -> str:
    return "till slutet" if p == 0 else f"{p} drag framåt"


class Settings(BaseModel):
    opponent_model: str = Field(PERFECT, pattern=f"^({PERFECT}|{HUMAN})$")
    plies: int = 2                                # 1–5, 10 eller 0 = till slutet
    candidates: int = Field(15, ge=1, le=60)
    iterations: int = Field(0, ge=0, le=100000)   # 0 = max inom tidsbudgeten
    sort: str = Field("win", pattern="^(win|margin)$")
    include_exchanges: bool = True
    seed: int = 1
    prune: bool = True
    workers: int = Field(0, ge=0, le=61)          # 0 = automatiskt (kärnor − 1)

    @field_validator("plies")
    @classmethod
    def _plies(cls, v: int) -> int:
        if v not in PLIES_OPTIONS:
            raise ValueError(f"plies måste vara något av {PLIES_OPTIONS} (0 = till slutet)")
        return v


class SettingsStore:
    def __init__(self, path: Path, defaults: dict) -> None:
        self.path = Path(path)
        self.defaults = Settings(**{k: v for k, v in defaults.items() if k in Settings.model_fields})

    def load(self) -> Settings:
        data = self.defaults.model_dump()
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in saved.items():
                    if k in Settings.model_fields:
                        merged = dict(data, **{k: v})
                        try:
                            Settings(**merged)          # hoppa över enstaka ogiltiga/gamla värden
                            data = merged
                        except ValueError:
                            pass
            except (OSError, ValueError):
                pass
        return Settings(**data)

    def save(self, s: Settings) -> Settings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(s.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
        return s


class BudgetError(ValueError):
    """Inte ens en iteration ryms inom tidsbudgeten."""

    def __init__(self, message: str, estimate: dict):
        super().__init__(message)
        self.estimate = estimate


class SimManager:
    def __init__(self, rules: Rules, sim_cfg: dict, dicts, dict_dir: Path,
                 workers: int | None = None) -> None:
        self.rules, self.cfg, self.dicts, self.dict_dir = rules, sim_cfg, dicts, dict_dir
        self.budget = dict(sim_cfg.get("budget", {}))
        self.fixed_workers = workers           # None = från inställningarna
        self.jobs: dict[str, tuple[str, Simulation]] = {}   # id -> (match-id, sim)
        self.current: str | None = None
        self._pool: WorkerPool | None = None
        self._lock = threading.Lock()
        self._cal_cache: OrderedDict[tuple, Calibration] = OrderedDict()
        self.leave = LeaveModel.from_config(sim_cfg["leave"], rules)

    # --- processpool ---
    def n_workers(self, s: Settings) -> int:
        if self.fixed_workers is not None:
            return self.fixed_workers
        return s.workers or auto_workers()

    def pool(self, n: int) -> WorkerPool:
        if self._pool is None or self._pool.workers != n:
            if self._pool is not None:
                self._pool.shutdown()
            self._pool = WorkerPool(self.rules.alphabet, self.dict_dir, n)
        return self._pool

    def warm(self, s: Settings, mode: str = "normal") -> None:
        n = self.n_workers(s)
        if n > 1 and self.dicts.base_exists(mode):
            self.pool(n).warm((mode, self.dicts.stamp(mode)))

    def shutdown(self) -> None:
        self.stop_all()
        if self._pool is not None:
            self._pool.shutdown()

    # --- förberedelse och budget ---
    def _prepare(self, g: Game, s: Settings):
        rules = self.rules
        board = g.board(rules)
        unseen = unseen_tiles(rules, board, g.rack)          # kastar vid felinmatning
        n_unseen = sum(unseen.values())
        bag = max(0, n_unseen - rules.rack_size)
        d = self.dicts.get(g.dict_mode)
        cands = select_candidates(board, g.rack, bag, d, self.leave, s.candidates,
                                  include_exchanges=s.include_exchanges,
                                  include_pass=s.include_exchanges)
        opp_cfg = self.cfg.get("opponent", {})
        ctx = SimContext(
            rules=rules, layout=tuple(g.layout),
            tiles=tuple((t["row"], t["col"], t["letter"], t["blank"]) for t in g.tiles),
            rack=g.rack, unseen=tuple(sorted(unseen.elements())),
            scores=(g.scores["me"], g.scores["opp"]), passes=g.consecutive_passes,
            leave_cfg=self.cfg["leave"], win_cfg=self.cfg["winmodel"],
            opponent_model=s.opponent_model,
            human_top_n=int(opp_cfg.get("human_top_n", 10)),
            human_temperature=float(opp_cfg.get("human_temperature", 8.0)),
            plies=s.plies, seed=s.seed)
        leaves = tuple(sorted({m.leave for m, _ in cands if "?" in m.leave}))
        key = (g.id, g.rack, g.dict_mode, self.dicts.stamp(g.dict_mode), leaves,
               tuple(sorted((t["row"], t["col"], t["letter"], t["blank"]) for t in g.tiles)))
        cal = self._cal_cache.get(key)
        if cal is None:
            cal = calibrate(ctx, d, self.leave,
                            int(self.budget.get("calibration_plain_samples", 4)),
                            int(self.budget.get("calibration_blank_samples", 2)), leaves,
                            int(self.budget.get("calibration_max_leaves", 6)))
            self._cal_cache[key] = cal
            while len(self._cal_cache) > 16:
                self._cal_cache.popitem(last=False)
        return ctx, cands, cal, bag, d

    def _estimate_dict(self, cal: Calibration, leaves: list[str], workers: int, s: Settings) -> dict:
        n_cands = len(leaves)
        plans = plan_all(cal, leaves, workers, self.budget)
        return {
            "max_seconds": float(self.budget.get("max_seconds", 60)),
            "candidates": n_cands, "workers": workers,
            "moves_left": moves_left(cal), "tiles_left": cal.tiles_left,
            "tiles_per_move": round(cal.tiles_per_move, 2),
            "ply_ms": round(1000 * cal.opp_seconds, 1),
            "kept_blanks": sum(1 for lv in leaves if "?" in lv),
            "kept_blank_ply_ms": round(1000 * max(cal.leave_seconds.values(), default=0), 1),
            "blank_share": round(cal.p_blank, 2),
            "calibration_ms": round(1000 * cal.seconds),
            "options": [p.as_dict() for p in plans],
            "selected": plan(cal, s.plies, leaves, workers, self.budget).as_dict(),
        }

    def estimate(self, g: Game, s: Settings) -> dict:
        _, cands, cal, _, _ = self._prepare(g, s)
        return self._estimate_dict(cal, [m.leave for m, _ in cands], self.n_workers(s), s)

    # --- jobb ---
    def stop_all(self) -> None:
        for _, sim in self.jobs.values():
            sim.stop()

    def start(self, g: Game, s: Settings) -> tuple[str, Simulation, list[str], dict]:
        rules = self.rules
        ctx, cands, cal, bag, d = self._prepare(g, s)
        n = self.n_workers(s)
        est = self._estimate_dict(cal, [m.leave for m, _ in cands], n, s)
        sel = est["selected"]
        max_it = sel["max_iterations"]
        if max_it < 1:
            options = [p for p in est["options"] if p["feasible"]]
            hint = (f" Längst möjliga just nu: {plies_label(max(options, key=lambda p: (p['plies'] == 0, p['plies']))['plies'])}."
                    if options else "")
            raise BudgetError(
                f"Simuleringen ryms inte inom {est['max_seconds']:.0f} s: en iteration med "
                f"{plies_label(s.plies)} och {len(cands)} kandidater beräknas ta "
                f"{sel['iteration_seconds']:.0f} s. Välj färre drag framåt eller färre kandidater.{hint}", est)
        iterations = max_it if s.iterations == 0 else min(s.iterations, max_it)
        notes = []
        if s.iterations > max_it:
            notes.append(f"{s.iterations} iterationer ryms inte inom {est['max_seconds']:.0f} s – "
                         f"kör {max_it} i stället.")
        if s.include_exchanges and bag < rules.exchange_min_bag:
            notes.append(f"Byte inte tillåtet: bara {bag} brickor i påsen")
        if bag == 0:
            notes.append("Påsen är tom – motståndarens hand är känd. Exakt slutspelssökning kommer i fas 5; "
                         "simuleringen ger en uppskattning.")
        job_id = uuid.uuid4().hex[:12]
        sim = Simulation(ctx, cands, SimSettings(iterations=iterations,
                                                 max_seconds=est["max_seconds"],
                                                 sort=s.sort, prune=s.prune), job_key=job_id)
        with self._lock:
            self.stop_all()
            self.jobs = {k: v for k, v in self.jobs.items() if v[1].status == "running"}
            self.jobs[job_id] = (g.id, sim)
            self.current = job_id
        if n > 1:
            pool = self.pool(n)
            stamp = self.dicts.stamp(g.dict_mode)
            target, args = sim.run_pool, (pool, g.dict_mode, stamp)
        else:
            target, args = sim.run_inline, (d,)
        threading.Thread(target=target, args=args, daemon=True).start()
        return job_id, sim, notes, est

    def get(self, job_id: str) -> Simulation | None:
        hit = self.jobs.get(job_id)
        return hit[1] if hit else None
