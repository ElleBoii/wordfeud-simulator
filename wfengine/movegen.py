"""Draggenerering (referensimplementation, Appel–Jacobson med DAWG).

Algoritmen är medvetet en annan än den GADDAG-baserade C++-versionen, så att
korstestningen jämför två oberoende implementationer.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import product

from .board import Board, Placement, rack_after
from .dictionary import Dictionary, Node
from .rules import BLANK


@dataclass(frozen=True)
class Move:
    kind: str                                  # "play", "exchange", "pass"
    placements: tuple[Placement, ...] = ()
    score: int = 0
    word: str = ""                             # huvudordet, blanka med gemen
    row: int = -1                              # huvudordets startruta
    col: int = -1
    horizontal: bool = True
    exchanged: str = ""                        # brickor som byts (vid byte)
    leave: str = ""                            # brickor kvar på hand

    @property
    def key(self):
        """Kanonisk identitet för ett drag, oberoende av hur det hittades."""
        if self.kind == "play":
            return ("play", self.placements)
        if self.kind == "exchange":
            return ("exchange", "".join(sorted(self.exchanged)))
        return ("pass",)

    def describe(self) -> str:
        if self.kind == "pass":
            return "Pass"
        if self.kind == "exchange":
            return f"Byt {self.exchanged}"
        d = "→" if self.horizontal else "↓"
        return f"{self.word} {self.row},{self.col}{d} {self.score}p"


def _cross_checks(cells, dictionary: Dictionary, size: int):
    """För varje tom ruta: mängd tillåtna bokstäver med hänsyn till lodräta ord,
    eller None om rutan saknar lodräta grannar (allt tillåtet)."""
    checks = [[None] * size for _ in range(size)]
    letters = None
    for r in range(size):
        for c in range(size):
            if cells[r][c] is not None:
                continue
            up = []
            rr = r - 1
            while rr >= 0 and cells[rr][c] is not None:
                up.append(cells[rr][c]); rr -= 1
            down = []
            rr = r + 1
            while rr < size and cells[rr][c] is not None:
                down.append(cells[rr][c]); rr += 1
            if not up and not down:
                continue
            prefix = "".join(reversed(up))
            suffix = "".join(down)
            node = dictionary.node_for_prefix(prefix)
            allowed = set()
            if node is not None:
                for ch, child in node.children.items():
                    n = child
                    for s in suffix:
                        n = n.children.get(s)
                        if n is None:
                            break
                    if n is not None and n.final:
                        allowed.add(ch)
            checks[r][c] = allowed
    return checks


def _anchors(cells, size: int, start, empty_board: bool):
    if empty_board:
        return [[(r, c) == tuple(start) for c in range(size)] for r in range(size)]
    a = [[False] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if cells[r][c] is not None:
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < size and 0 <= cc < size and cells[rr][cc] is not None:
                    a[r][c] = True
                    break
    return a


def _gen_across(cells, dictionary: Dictionary, rack: Counter, size: int, start, empty_board: bool):
    """Genererar vågräta drag på 'cells'. Ger listor av (row, col, letter, blank)."""
    checks = _cross_checks(cells, dictionary, size)
    anchors = _anchors(cells, size, start, empty_board)
    found = []

    for r in range(size):
        row = cells[r]
        chk = checks[r]
        for anchor in range(size):
            if not anchors[r][anchor]:
                continue

            def extend_right(node: Node, col: int, placed: list):
                if col >= size or row[col] is None:
                    if col > anchor and node.final and placed:
                        found.append(list(placed))
                    if col >= size:
                        return
                    allowed = chk[col]
                    for ch, child in node.children.items():
                        if allowed is not None and ch not in allowed:
                            continue
                        if rack[ch] > 0:
                            rack[ch] -= 1
                            placed.append((r, col, ch, False))
                            extend_right(child, col + 1, placed)
                            placed.pop()
                            rack[ch] += 1
                        if rack[BLANK] > 0:
                            rack[BLANK] -= 1
                            placed.append((r, col, ch, True))
                            extend_right(child, col + 1, placed)
                            placed.pop()
                            rack[BLANK] += 1
                else:
                    child = node.children.get(row[col])
                    if child is not None:
                        extend_right(child, col + 1, placed)

            if anchor > 0 and row[anchor - 1] is not None:
                # Vänsterdelen är redan lagda brickor.
                c = anchor - 1
                while c > 0 and row[c - 1] is not None:
                    c -= 1
                node = dictionary.node_for_prefix("".join(row[c:anchor]))
                if node is not None:
                    extend_right(node, anchor, [])
                continue

            # Vänsterdelen läggs från handen på tomma rutor som inte är ankare.
            limit = 0
            c = anchor - 1
            while c >= 0 and row[c] is None and not anchors[r][c]:
                limit += 1
                c -= 1

            def left_part(node: Node, left: list, room: int):
                # 'left' innehåller (letter, blank) för vänsterdelen, i ordning.
                n = len(left)
                placed = [(r, anchor - n + i, ch, b) for i, (ch, b) in enumerate(left)]
                extend_right(node, anchor, placed)
                if room == 0:
                    return
                for ch, child in node.children.items():
                    if rack[ch] > 0:
                        rack[ch] -= 1
                        left.append((ch, False))
                        left_part(child, left, room - 1)
                        left.pop()
                        rack[ch] += 1
                    if rack[BLANK] > 0:
                        rack[BLANK] -= 1
                        left.append((ch, True))
                        left_part(child, left, room - 1)
                        left.pop()
                        rack[BLANK] += 1

            left_part(dictionary.root, [], limit)
    return found


def generate_plays(board: Board, rack: str, dictionary: Dictionary) -> list[Move]:
    """Alla lagliga läggningar (inga byten/pass), unika och med poäng."""
    size = board.size
    cells = board.letters_grid()
    empty = board.is_empty_board()
    counts = Counter(rack)
    start = board.rules.start

    raw = []
    for pl in _gen_across(cells, dictionary, counts, size, start, empty):
        raw.append(tuple(Placement(r, c, ch, b) for r, c, ch, b in pl))
    transposed = [list(col) for col in zip(*cells)]
    for pl in _gen_across(transposed, dictionary, counts, size, (start[1], start[0]), empty):
        raw.append(tuple(Placement(c, r, ch, b) for r, c, ch, b in pl))

    moves = {}
    for pl in raw:
        pl = tuple(sorted(pl))
        if pl in moves:
            continue
        res = board.evaluate(pl)
        if not res.ok:   # ska inte hända; skydd mot buggar
            raise AssertionError(f"Genererat ogiltigt drag {pl}: {res.errors}")
        w = res.main_word
        moves[pl] = Move("play", pl, res.score, w.text, w.row, w.col, w.horizontal,
                         leave=rack_after(rack, pl))
    return list(moves.values())


def generate_exchanges(rack: str) -> list[Move]:
    """Alla unika icke-tomma delmängder av handen."""
    counts = sorted(Counter(rack).items())
    out = []
    for choice in product(*(range(n + 1) for _, n in counts)):
        if sum(choice) == 0:
            continue
        ex = "".join(ch * k for (ch, _), k in zip(counts, choice))
        leave = "".join(ch * (n - k) for (ch, n), k in zip(counts, choice))
        out.append(Move("exchange", exchanged=ex, leave=leave))
    return out


def generate_moves(board: Board, rack: str, dictionary: Dictionary,
                   bag_count: int | None = None, include_exchanges: bool = True,
                   include_pass: bool = True) -> list[Move]:
    """Läggningar + byten (om påsen har minst exchange_min_bag brickor) + pass."""
    moves = generate_plays(board, rack, dictionary)
    if include_exchanges and rack and bag_count is not None and bag_count >= board.rules.exchange_min_bag:
        moves += generate_exchanges(rack)
    if include_pass:
        moves.append(Move("pass", leave=rack))
    return moves
