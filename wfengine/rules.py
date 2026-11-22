"""Laddning av spelregler från config/rules_sv.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BLANK = "?"

# Bonuskoder i layouten.
NONE, DL, TL, DW, TW = ".", "d", "t", "D", "T"
BONUS_CODES = {NONE, DL, TL, DW, TW}
LETTER_MULT = {NONE: 1, DL: 2, TL: 3, DW: 1, TW: 1}
WORD_MULT = {NONE: 1, DL: 1, TL: 1, DW: 2, TW: 3}

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "rules_sv.json"


@dataclass(frozen=True)
class Rules:
    alphabet: str
    counts: dict[str, int]          # antal per bokstav, inkl. BLANK
    values: dict[str, int]          # poäng per bokstav, BLANK = 0
    rack_size: int
    bingo_tiles: int
    bingo_bonus: int
    exchange_min_bag: int
    size: int
    start: tuple[int, int]
    standard_layout: tuple[str, ...]
    end_of_game: dict = field(default_factory=dict)
    unverified: tuple[str, ...] = ()   # sektioner som ännu inte verifierats

    @property
    def total_tiles(self) -> int:
        return sum(self.counts.values())

    def value(self, letter: str, is_blank: bool = False) -> int:
        return 0 if is_blank else self.values[letter]


def load_rules(path: str | Path = DEFAULT_CONFIG) -> Rules:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    alphabet = data["alphabet"]
    letters = data["tiles"]["letters"]
    missing = set(alphabet) - set(letters)
    extra = set(letters) - set(alphabet)
    if missing or extra:
        raise ValueError(f"Brickfördelning matchar inte alfabetet: saknas {sorted(missing)}, extra {sorted(extra)}")
    counts = {ch: int(letters[ch][0]) for ch in alphabet}
    values = {ch: int(letters[ch][1]) for ch in alphabet}
    counts[BLANK] = int(data["tiles"]["blanks"])
    values[BLANK] = 0

    board = data["board"]
    size = int(board["size"])
    layout = tuple(board["standard_layout"])
    validate_layout(layout, size)

    unverified = tuple(
        name for name, ok in [
            ("tiles", data["tiles"].get("verified")),
            ("bingo", data["bingo"].get("verified")),
            ("exchange", data["exchange"].get("verified")),
            ("end_of_game", data["end_of_game"].get("verified")),
            ("standard_layout", board.get("standard_layout_verified")),
        ] if not ok
    )

    return Rules(
        alphabet=alphabet,
        counts=counts,
        values=values,
        rack_size=int(data["rack_size"]),
        bingo_tiles=int(data["bingo"]["tiles"]),
        bingo_bonus=int(data["bingo"]["bonus"]),
        exchange_min_bag=int(data["exchange"]["min_bag"]),
        size=size,
        start=tuple(board["start"]),
        standard_layout=layout,
        end_of_game={k: v for k, v in data["end_of_game"].items() if not k.startswith("_")},
        unverified=unverified,
    )


def validate_layout(layout, size: int) -> None:
    if len(layout) != size or any(len(row) != size for row in layout):
        raise ValueError(f"Bonuslayouten måste vara {size}x{size}")
    bad = {c for row in layout for c in row} - BONUS_CODES
    if bad:
        raise ValueError(f"Okända bonuskoder i layout: {sorted(bad)}")


# --- Matchslut ---------------------------------------------------------------

def rack_value(rules: Rules, rack: str) -> int:
    return sum(rules.values[ch] for ch in rack)


def is_game_over(rules: Rules, consecutive_passes: int, bag_count: int, racks: list[str]) -> bool:
    """Slut om någon gått ut (tom hand, tom påse) eller efter N pass i rad totalt."""
    if consecutive_passes >= rules.end_of_game["consecutive_passes_to_end"]:
        return True
    return bag_count == 0 and any(len(r) == 0 for r in racks)


def update_pass_count(rules: Rules, consecutive_passes: int, move_kind: str) -> int:
    """Nytt antal pass i rad efter ett drag ('play', 'exchange' eller 'pass')."""
    if move_kind == "pass":
        return consecutive_passes + 1
    if move_kind == "exchange" and rules.end_of_game.get("exchange_counts_as_pass", False):
        return consecutive_passes + 1
    return 0


def final_adjustments(rules: Rules, racks: list[str]) -> list[int]:
    """Poängjustering per spelare vid matchslut, givet kvarvarande händer.
    Var och en tappar sin egen handsumma; den som gått ut (tom hand) får
    dessutom övrigas handsummor."""
    eog = rules.end_of_game
    values = [rack_value(rules, r) for r in racks]
    adj = [-v if eog.get("subtract_own_rack", True) else 0 for v in values]
    if eog.get("going_out_adds_opponent_rack", True):
        for i, r in enumerate(racks):
            if not r:
                adj[i] += sum(v for j, v in enumerate(values) if j != i)
    return adj
