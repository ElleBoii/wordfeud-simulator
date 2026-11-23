"""Snabb draggenerering med inbyggd poängräkning (för simuleringen).

Samma algoritm som movegen.py (Appel–Jacobson på DAWG), men poängen räknas
under genereringen i stället för med Board.evaluate i efterhand, och dragen
returneras som lätta tupler. Ungefär 4–5 gånger snabbare. Korstestas mot
movegen.generate_plays (samma dragmängd, samma poäng) i tests/test_fastgen.py.

Ett drag är (poäng, placeringar), där placeringar är en tupel av
(rad, kolumn, bokstav, blank).
"""
from __future__ import annotations

from collections import Counter

from .board import Board
from .dictionary import Dictionary
from .rules import BLANK, LETTER_MULT, WORD_MULT


def _grids(board: Board):
    size = board.size
    values = board.rules.values
    cells = [[None] * size for _ in range(size)]
    vals = [[0] * size for _ in range(size)]
    for r, c, t in board.tiles():
        cells[r][c] = t.letter
        vals[r][c] = 0 if t.blank else values[t.letter]
    lm = [[LETTER_MULT[ch] for ch in row] for row in board.layout]
    wm = [[WORD_MULT[ch] for ch in row] for row in board.layout]
    return cells, vals, lm, wm


def _transpose(g):
    return [list(col) for col in zip(*g)]


def _cross(cells, vals, dictionary: Dictionary, size: int):
    """Per tom ruta: tillåtna bokstäver (None = allt) och summan av de lodräta
    grannarnas brickvärden (-1 = inget korsord)."""
    checks = [[None] * size for _ in range(size)]
    xsum = [[-1] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            if cells[r][c] is not None:
                continue
            up_ok = r > 0 and cells[r - 1][c] is not None
            down_ok = r < size - 1 and cells[r + 1][c] is not None
            if not up_ok and not down_ok:
                continue
            s = 0
            rr = r - 1
            up = []
            while rr >= 0 and cells[rr][c] is not None:
                up.append(cells[rr][c]); s += vals[rr][c]; rr -= 1
            down = []
            rr = r + 1
            while rr < size and cells[rr][c] is not None:
                down.append(cells[rr][c]); s += vals[rr][c]; rr += 1
            node = dictionary.node_for_prefix("".join(reversed(up)))
            allowed = set()
            if node is not None:
                for ch, child in node.children.items():
                    n = child
                    for x in down:
                        n = n.children.get(x)
                        if n is None:
                            break
                    if n is not None and n.final:
                        allowed.add(ch)
            checks[r][c] = allowed
            xsum[r][c] = s
    return checks, xsum


def _anchors(cells, size: int, start, empty_board: bool):
    if empty_board:
        return [[(r, c) == tuple(start) for c in range(size)] for r in range(size)]
    a = [[False] * size for _ in range(size)]
    for r in range(size):
        row = cells[r]
        for c in range(size):
            if row[c] is not None:
                continue
            if ((c > 0 and row[c - 1] is not None) or (c < size - 1 and row[c + 1] is not None)
                    or (r > 0 and cells[r - 1][c] is not None)
                    or (r < size - 1 and cells[r + 1][c] is not None)):
                a[r][c] = True
    return a


def _gen(cells, vals, lm, wm, dictionary, rack: Counter, values, size, start, empty_board,
         bingo_tiles, bingo_bonus, out, transposed):
    checks, xsum = _cross(cells, vals, dictionary, size)
    anchors = _anchors(cells, size, start, empty_board)
    root = dictionary.root

    for r in range(size):
        row = cells[r]
        vrow = vals[r]
        lrow = lm[r]
        wrow = wm[r]
        chk = checks[r]
        xs = xsum[r]
        arow = anchors[r]
        for anchor in range(size):
            if not arow[anchor]:
                continue

            def extend_right(node, col, placed, main, mult, cross):
                if col >= size or row[col] is None:
                    if col > anchor and node.final and placed:
                        n = len(placed)
                        score = main * mult + cross + (bingo_bonus if n == bingo_tiles else 0)
                        if transposed:
                            # Enbrickslag som också bildar ett vågrätt ord (= korsord här)
                            # hittades redan i det vågräta passet.
                            if n > 1 or xs[placed[0][1]] < 0:
                                out.append((score, tuple((c, rr, ch, b) for rr, c, ch, b in placed)))
                        else:
                            out.append((score, tuple(placed)))
                    if col >= size:
                        return
                    allowed = chk[col]
                    l_m = lrow[col]
                    w_m = wrow[col]
                    x = xs[col]
                    for ch, child in node.children.items():
                        if allowed is not None and ch not in allowed:
                            continue
                        if rack[ch] > 0:
                            v = values[ch] * l_m
                            rack[ch] -= 1
                            placed.append((r, col, ch, False))
                            extend_right(child, col + 1, placed, main + v, mult * w_m,
                                         cross + ((x + v) * w_m if x >= 0 else 0))
                            placed.pop()
                            rack[ch] += 1
                        if rack[BLANK] > 0:
                            rack[BLANK] -= 1
                            placed.append((r, col, ch, True))
                            extend_right(child, col + 1, placed, main, mult * w_m,
                                         cross + (x * w_m if x >= 0 else 0))
                            placed.pop()
                            rack[BLANK] += 1
                else:
                    child = node.children.get(row[col])
                    if child is not None:
                        extend_right(child, col + 1, placed, main + vrow[col], mult, cross)

            if anchor > 0 and row[anchor - 1] is not None:
                c = anchor - 1
                s = 0
                while c > 0 and row[c - 1] is not None:
                    c -= 1
                for k in range(c, anchor):
                    s += vrow[k]
                node = dictionary.node_for_prefix("".join(row[c:anchor]))
                if node is not None:
                    extend_right(node, anchor, [], s, 1, 0)
                continue

            limit = 0
            c = anchor - 1
            while c >= 0 and row[c] is None and not arow[c]:
                limit += 1
                c -= 1

            def left_part(node, left, room):
                n = len(left)
                placed = []
                main = 0
                mult = 1
                base = anchor - n
                for i, (ch, b) in enumerate(left):
                    col = base + i
                    placed.append((r, col, ch, b))
                    if not b:
                        main += values[ch] * lrow[col]
                    mult *= wrow[col]
                extend_right(node, anchor, placed, main, mult, 0)
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

            left_part(root, [], limit)


def scored_plays(board: Board, rack: str, dictionary: Dictionary) -> list[tuple[int, tuple]]:
    """Alla lagliga läggningar som (poäng, ((rad, kol, bokstav, blank), ...)).
    Varje drag förekommer exakt en gång."""
    if not rack:
        return []
    rules = board.rules
    size = board.size
    cells, vals, lm, wm = _grids(board)
    empty = board.is_empty_board()
    counts = Counter(rack)
    out: list[tuple[int, tuple]] = []
    args = (rules.values, size)
    _gen(cells, vals, lm, wm, dictionary, counts, *args, rules.start, empty,
         rules.bingo_tiles, rules.bingo_bonus, out, False)
    _gen(_transpose(cells), _transpose(vals), _transpose(lm), _transpose(wm), dictionary, counts,
         *args, (rules.start[1], rules.start[0]), empty, rules.bingo_tiles, rules.bingo_bonus, out, True)
    return out
