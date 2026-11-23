"""Statisk värdering: leave-värden och vinstmodell (version 1, heuristiska).

Parametrarna ligger i config/sim_sv.json. Leave-värden kan ersättas med en
tränad tabell (version 2) via leave.table_file: JSON {"AERS": 12.3, ...} där
nyckeln är leaven sorterad (blank = '?'). Finns leaven i tabellen används
tabellvärdet, annars heuristiken.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from .rules import BLANK, Rules

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIM_CONFIG = ROOT / "config" / "sim_sv.json"


def load_sim_config(path: str | Path = DEFAULT_SIM_CONFIG) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _strip_comments(data)


def _strip_comments(d):
    if isinstance(d, dict):
        return {k: _strip_comments(v) for k, v in d.items() if not k.startswith("_")}
    return d


class LeaveModel:
    def __init__(self, cfg: dict, rules: Rules, table: dict[str, float] | None = None) -> None:
        self.rules = rules
        self.tiles = {k: float(v) for k, v in cfg.get("tiles", {}).items()}
        self.duplicate = float(cfg.get("duplicate", 0))
        self.duplicate_blank = float(cfg.get("duplicate_blank", self.duplicate))
        self.vowels = set(cfg.get("vowels", ""))
        self.balance_free = int(cfg.get("balance_free", 1))
        self.balance_penalty = float(cfg.get("balance_penalty", 0))
        self.empty_bag_factor = float(cfg.get("empty_bag_factor", 1.0))
        self.table = dict(table or {})
        self._cache: dict[str, float] = {}

    @classmethod
    def from_config(cls, cfg: dict, rules: Rules) -> "LeaveModel":
        table = None
        tf = cfg.get("table_file")
        if tf:
            p = Path(tf)
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                table = {"".join(sorted(k)): float(v)
                         for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
        return cls(cfg, rules, table)

    def value(self, leave: str, bag_empty: bool = False) -> float:
        """Värdet av att ha 'leave' kvar på hand. När påsen är tom kan inget fyllas
        på, och brickorna på hand räknas då som minuspoäng."""
        if bag_empty:
            return -self.empty_bag_factor * sum(self.rules.values[ch] for ch in leave)
        key = "".join(sorted(leave))
        v = self._cache.get(key)
        if v is None:
            v = self.table[key] if key in self.table else self._heuristic(key)
            self._cache[key] = v
        return v

    def _heuristic(self, key: str) -> float:
        if not key:
            return 0.0
        counts = Counter(key)
        total = 0.0
        for ch, n in counts.items():
            total += self.tiles.get(ch, 0.0)
            if n > 1:
                total -= (n - 1) * (self.duplicate_blank if ch == BLANK else self.duplicate)
        v = sum(n for ch, n in counts.items() if ch in self.vowels)
        c = sum(n for ch, n in counts.items() if ch != BLANK and ch not in self.vowels)
        excess = abs(v - c) - self.balance_free
        if excess > 0:
            total -= excess * self.balance_penalty
        return total


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class WinModel:
    """Version 1: P(vinst) = Φ((marginal ± turbonus) / σ(osedda))."""

    def __init__(self, cfg: dict, rules: Rules) -> None:
        self.k = float(cfg.get("sigma_per_sqrt_tile", 7.0))
        self.sigma_min = float(cfg.get("sigma_min", 4.0))
        self.turn_bonus = float(cfg.get("turn_bonus", 0.0))
        self.rack_size = rules.rack_size

    def sigma(self, unseen: int) -> float:
        return max(self.sigma_min, self.k * math.sqrt(max(0, unseen)))

    def win_prob(self, margin: float, unseen: int, my_turn: bool) -> float:
        """margin = min poäng − motståndarens (inkl. leave-värden); unseen = osedda
        brickor från min sida (påse + motståndarens hand)."""
        scale = min(1.0, unseen / (2 * self.rack_size)) if self.rack_size else 1.0
        m = margin + (self.turn_bonus if my_turn else -self.turn_bonus) * scale
        return normal_cdf(m / self.sigma(unseen))
