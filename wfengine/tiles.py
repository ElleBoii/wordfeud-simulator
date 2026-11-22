"""Osedda brickor: full fördelning − brickor på brädet − min hand."""
from __future__ import annotations

from collections import Counter

from .board import Board
from .rules import BLANK, Rules


class TileCountError(ValueError):
    """Fler brickor av någon sort än fördelningen tillåter – något är felinmatat."""

    def __init__(self, excess: dict[str, int]):
        self.excess = excess
        parts = ", ".join(f"{'blank' if k == BLANK else k}: {v} för många" for k, v in sorted(excess.items()))
        super().__init__(f"Brickorna överskrider fördelningen ({parts})")


def unseen_tiles(rules: Rules, board: Board, rack: str) -> Counter:
    used = Counter()
    for _, _, t in board.tiles():
        used[BLANK if t.blank else t.letter] += 1
    for ch in rack:
        used[ch] += 1
    unknown = set(used) - set(rules.counts)
    if unknown:
        raise ValueError(f"Okända brickor: {sorted(unknown)}")
    excess = {k: v - rules.counts[k] for k, v in used.items() if v > rules.counts[k]}
    if excess:
        raise TileCountError(excess)
    return Counter({k: n - used[k] for k, n in rules.counts.items() if n - used[k] > 0})


def bag_count(rules: Rules, unseen: Counter) -> int:
    """Brickor i påsen = osedda − motståndarens hand (högst rack_size)."""
    return max(0, sum(unseen.values()) - rules.rack_size)


def opponent_rack_size(rules: Rules, unseen: Counter) -> int:
    return min(rules.rack_size, sum(unseen.values()))
