"""Tidsbudget för simuleringen: hur många iterationer hinns inom maxtiden?

1. calibrate(): mäter i den aktuella ställningen hur lång tid ett policydrag
   (generera alla drag + välj bästa) tar:
   - för motståndaren: slumpade händer ur de osedda brickorna. Händer med och
     utan blank mäts var för sig och vägs ihop med sannolikheten att en hand
     innehåller blank (blank kostar 10–40x).
   - för mig: när en kandidat behåller blanka (byten, pass, drag som sparar
     blanken) görs mitt första drag i rolluten med blanka på hand. Det mäts
     med kandidatens faktiska kvarvarande brickor (fyllda med slumpade osedda),
     eftersom t.ex. AR?TL?E ger många fler drag än en slumpad hand med två
     blanka. Händer med 1 och 2 slumpade blanka mäts som reserv.
   Samma mätning ger hur många brickor ett typiskt drag använder.
2. plan(): uppskattat antal drag kvar i matchen = brickor kvar / brickor per
   drag. Effektiva drag per rollout = min(valt antal, drag kvar), växelvis
   motståndaren (först) och jag. Kostnaden räknas per kandidat:
     motståndardrag × t_motst + mitt första drag med kandidatens leave
     + övriga egna drag med k−1, k−2, … blanka.
   Tid per iteration = summa över kandidaterna / (processer × verkningsgrad).
   Max iterationer = budget / tid per iteration.

Uppskattningen är grov; simuleringen har därför också en hård tidsgräns.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .dictionary import Dictionary
from .evaluation import LeaveModel
from .rules import BLANK
from .sim import END_PLIES, SimContext, choose

PLIES_OPTIONS = (1, 2, 3, 4, 5, 10, 0)        # 0 = till slutet


@dataclass
class Calibration:
    opp_seconds: float                # förväntad tid för ett motståndardrag
    plain_seconds: float              # medel för händer utan blank
    blank_seconds: dict[int, float]   # medel för händer med k blanka (k = 1, 2)
    p_blank: float                    # sannolikhet att motståndarens hand har blank
    tiles_per_move: float             # brickor per lagt drag
    tiles_left: int                   # brickor som inte ligger på brädet (påse + båda händer)
    seconds: float                    # hur lång tid kalibreringen tog
    leave_seconds: dict[str, float] = field(default_factory=dict)  # mitt drag efter en viss leave

    @property
    def ply_seconds(self) -> float:   # bakåtkompatibelt namn
        return self.opp_seconds

    def my_ply(self, blanks: int) -> float:
        """Tid för mitt drag med 'blanks' blanka på hand (0 = som motståndarens)."""
        if blanks <= 0:
            return self.opp_seconds
        k = min(blanks, 2)
        if k in self.blank_seconds:
            return self.blank_seconds[k]
        return max(self.blank_seconds.values(), default=self.opp_seconds)


def _p_any_blank(unseen: list[str], k: int) -> float:
    n, b = len(unseen), unseen.count(BLANK)
    if b == 0 or k == 0:
        return 0.0
    if n - b < k:
        return 1.0
    return 1.0 - math.comb(n - b, k) / math.comb(n, k)


def calibrate(ctx: SimContext, dictionary: Dictionary, leave: LeaveModel,
              plain_samples: int = 4, blank_samples: int = 2,
              my_leaves: list[str] | tuple[str, ...] = (), max_leaves: int = 6,
              seed: int = 12345) -> Calibration:
    """my_leaves: kandidaternas kvarvarande brickor (bara de med blanka mäts,
    högst max_leaves olika; flest blanka först)."""
    t0 = time.perf_counter()
    rules = ctx.rules
    board = ctx.board()
    unseen = list(ctx.unseen)
    k = min(rules.rack_size, len(unseen))
    bag_len = max(0, len(unseen) - k)
    rng = random.Random(seed)
    plain_pool = [t for t in unseen if t != BLANK] + [t for t in ctx.rack if t != BLANK]
    used: list[int] = []

    def measure(racks):
        times = []
        for rack in racks:
            s = time.perf_counter()
            ch = choose(board, rack, bag_len, dictionary, leave, rules)
            times.append(time.perf_counter() - s)
            if ch.kind == "play":
                used.append(len(ch.used))
        return sum(times) / len(times) if times else 0.0

    def racks_with(nb: int, n: int):
        size = max(nb, min(rules.rack_size, len(plain_pool) + nb))
        return ["".join(rng.sample(plain_pool, size - nb)) + BLANK * nb for _ in range(n)]

    t_plain = measure(racks_with(0, plain_samples)) if plain_pool else 0.0
    with_blank = sorted({lv for lv in my_leaves if BLANK in lv}, key=lambda lv: (-lv.count(BLANK), lv))
    needed = {min(2, lv.count(BLANK)) for lv in with_blank}
    if BLANK in unseen:
        needed.add(1)
    blank_t = {}
    for nb in sorted(min(b, 2) for b in needed):
        if nb not in blank_t:
            # Två blanka kostar mycket; ett prov räcker för en grov nivå.
            blank_t[nb] = measure(racks_with(nb, blank_samples if nb == 1 else 1))
    leave_t = {}
    fill = [t for t in unseen if t != BLANK]
    for lv in with_blank[:max_leaves]:
        n_fill = min(len(fill), rules.rack_size - len(lv))
        leave_t[lv] = measure([lv + "".join(rng.sample(fill, n_fill))])
    p = _p_any_blank(unseen, k)
    t_opp = (1 - p) * t_plain + p * blank_t.get(1, t_plain)
    tpm = sum(used) / len(used) if used else 3.0
    tpm = min(float(rules.rack_size), max(1.5, tpm))
    return Calibration(opp_seconds=max(t_opp, 1e-4), plain_seconds=t_plain, blank_seconds=blank_t,
                       p_blank=p, tiles_per_move=tpm, tiles_left=len(unseen) + len(ctx.rack),
                       seconds=time.perf_counter() - t0, leave_seconds=leave_t)


def moves_left(cal: Calibration) -> int:
    """Uppskattat antal drag kvar i matchen (båda spelarna), inkl. ett par i slutspelet."""
    return max(1, math.ceil(cal.tiles_left / cal.tiles_per_move) + 1)


def effective_plies(plies: int, cal: Calibration) -> int:
    """Drag efter kandidaten som en rollout i snitt spelar (kandidaten räknas som ett drag)."""
    left = max(0, moves_left(cal) - 1)
    full = END_PLIES if plies == 0 else plies
    return min(full, left)


def rollout_seconds(cal: Calibration, eff: int, leave: str) -> float:
    """Uppskattad tid för en rollout med 'eff' drag efter en kandidat som lämnar
    'leave' på min hand. Varannat drag: motståndaren först."""
    n_opp = (eff + 1) // 2
    n_me = eff // 2
    kept = leave.count(BLANK)
    t = n_opp * cal.opp_seconds
    for j in range(n_me):
        if j == 0 and leave in cal.leave_seconds:
            t += cal.leave_seconds[leave]
        else:
            t += cal.my_ply(kept - j)          # antag att en blank förbrukas per eget drag
    return t


@dataclass
class Plan:
    plies: int
    effective_plies: int
    iteration_seconds: float      # uppskattad tid per iteration (alla kandidater)
    max_iterations: int           # 0 = inte möjligt inom budgeten

    def as_dict(self) -> dict:
        return {"plies": self.plies, "effective_plies": self.effective_plies,
                "iteration_seconds": round(self.iteration_seconds, 3),
                "max_iterations": self.max_iterations, "feasible": self.max_iterations >= 1}


def plan(cal: Calibration, plies: int, leaves: list[str], workers: int, cfg: dict) -> Plan:
    """leaves: för varje kandidat, brickorna den lämnar kvar på min hand."""
    eff = effective_plies(plies, cal)
    overhead = float(cfg.get("rollout_overhead_seconds", 0.002))
    par = workers * (float(cfg.get("parallel_efficiency", 0.75)) if workers > 1 else 1.0)
    total = sum(rollout_seconds(cal, eff, lv) + overhead for lv in (leaves or [""]))
    it_s = total * float(cfg.get("cost_factor", 1.0)) / par
    budget = float(cfg.get("max_seconds", 60)) * float(cfg.get("safety", 0.85))
    n = int(budget // it_s) if it_s > 0 else 0
    return Plan(plies, eff, it_s, min(n, int(cfg.get("max_iterations", 5000))))


def plan_all(cal: Calibration, leaves: list[str], workers: int, cfg: dict) -> list[Plan]:
    return [plan(cal, p, leaves, workers, cfg) for p in PLIES_OPTIONS]
