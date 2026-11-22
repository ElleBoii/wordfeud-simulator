"""Bräde, drag och poängräkning (referensimplementation i ren Python)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .rules import BLANK, LETTER_MULT, WORD_MULT, Rules, validate_layout


@dataclass(frozen=True, order=True)
class Placement:
    row: int
    col: int
    letter: str        # alltid versal, även för blank (vald bokstav)
    blank: bool = False


@dataclass(frozen=True)
class Tile:
    letter: str
    blank: bool = False


@dataclass(frozen=True)
class Word:
    text: str          # versaler; blanka visas med gemen
    row: int
    col: int
    horizontal: bool
    score: int

    @property
    def plain(self) -> str:
        return self.text.upper()


@dataclass
class PlayResult:
    placements: tuple[Placement, ...]
    words: list[Word] = field(default_factory=list)   # huvudordet först
    score: int = 0
    bingo: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def main_word(self) -> Word | None:
        return self.words[0] if self.words else None


class Board:
    def __init__(self, rules: Rules, layout=None) -> None:
        self.rules = rules
        self.size = rules.size
        self.layout = tuple(layout) if layout is not None else rules.standard_layout
        validate_layout(self.layout, self.size)
        self.grid: list[list[Tile | None]] = [[None] * self.size for _ in range(self.size)]

    # --- grundläggande ---------------------------------------------------
    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b.rules, b.size, b.layout = self.rules, self.size, self.layout
        b.grid = [row[:] for row in self.grid]
        return b

    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.size and 0 <= c < self.size

    def get(self, r: int, c: int) -> Tile | None:
        return self.grid[r][c] if self.in_bounds(r, c) else None

    def occupied(self, r: int, c: int) -> bool:
        return self.in_bounds(r, c) and self.grid[r][c] is not None

    def is_empty_board(self) -> bool:
        return all(t is None for row in self.grid for t in row)

    def tiles(self):
        for r in range(self.size):
            for c in range(self.size):
                t = self.grid[r][c]
                if t is not None:
                    yield r, c, t

    def bonus(self, r: int, c: int) -> str:
        return self.layout[r][c]

    def letters_grid(self) -> list[list[str | None]]:
        return [[t.letter if t else None for t in row] for row in self.grid]

    def apply(self, placements) -> None:
        for p in placements:
            if self.grid[p.row][p.col] is not None:
                raise ValueError(f"Rutan {p.row},{p.col} är upptagen")
            self.grid[p.row][p.col] = Tile(p.letter, p.blank)

    def remove(self, placements) -> None:
        for p in placements:
            self.grid[p.row][p.col] = None

    def __str__(self) -> str:
        lines = []
        for r in range(self.size):
            row = []
            for c in range(self.size):
                t = self.grid[r][c]
                row.append((t.letter.lower() if t.blank else t.letter) if t else self.layout[r][c])
            lines.append(" ".join(row))
        return "\n".join(lines)

    # --- manuell inmatning ----------------------------------------------
    def placements_for_word(self, row: int, col: int, horizontal: bool, text: str) -> list[Placement]:
        """Gör om 'HUSet' lagt från (row, col) till placeringar. Gemener = blank.
        Rutor som redan har en bricka hoppas över (bokstaven måste stämma)."""
        dr, dc = (0, 1) if horizontal else (1, 0)
        out = []
        for i, ch in enumerate(text):
            r, c = row + dr * i, col + dc * i
            if not self.in_bounds(r, c):
                raise ValueError("Ordet går utanför brädet")
            letter = ch.upper()
            existing = self.grid[r][c]
            if existing is not None:
                if existing.letter != letter:
                    raise ValueError(f"Rutan {r},{c} har redan {existing.letter}, inte {letter}")
                continue
            out.append(Placement(r, c, letter, ch.islower()))
        return out

    # --- poängräkning och validering ------------------------------------
    def _word_through(self, r: int, c: int, horizontal: bool, new: dict) -> tuple[int, int, list]:
        """Hela ordet genom (r, c) i given riktning, med nya brickor 'new' {(r,c): Placement}."""
        dr, dc = (0, 1) if horizontal else (1, 0)

        def at(rr, cc):
            if (rr, cc) in new:
                return new[(rr, cc)]
            return self.get(rr, cc)

        sr, sc = r, c
        while self.in_bounds(sr - dr, sc - dc) and at(sr - dr, sc - dc) is not None:
            sr, sc = sr - dr, sc - dc
        cells = []
        rr, cc = sr, sc
        while self.in_bounds(rr, cc) and at(rr, cc) is not None:
            cells.append((rr, cc, at(rr, cc), (rr, cc) in new))
            rr, cc = rr + dr, cc + dc
        return sr, sc, cells

    def _score_cells(self, cells) -> tuple[str, int]:
        values = self.rules.values
        total, mult, text = 0, 1, []
        for r, c, t, is_new in cells:
            v = 0 if t.blank else values[t.letter]
            if is_new:
                b = self.layout[r][c]
                v *= LETTER_MULT[b]
                mult *= WORD_MULT[b]
            total += v
            text.append(t.letter.lower() if t.blank else t.letter)
        return "".join(text), total * mult

    def evaluate(self, placements) -> PlayResult:
        """Kontrollerar placeringens geometri och räknar poäng för alla ord som bildas.
        Kontrollerar INTE om orden finns i ordlistan."""
        placements = tuple(sorted(placements))
        res = PlayResult(placements)
        if not placements:
            res.errors.append("Inga brickor lagda")
            return res
        new = {}
        for p in placements:
            if not self.in_bounds(p.row, p.col):
                res.errors.append(f"Ruta {p.row},{p.col} är utanför brädet")
            elif self.grid[p.row][p.col] is not None:
                res.errors.append(f"Ruta {p.row},{p.col} är redan upptagen")
            elif (p.row, p.col) in new:
                res.errors.append(f"Ruta {p.row},{p.col} används två gånger")
            new[(p.row, p.col)] = p
        if res.errors:
            return res

        rows = {p.row for p in placements}
        cols = {p.col for p in placements}
        if len(rows) == 1 and len(cols) == 1:
            r, c = placements[0].row, placements[0].col
            h_len = len(self._word_through(r, c, True, new)[2])
            horizontal = h_len >= 2 or len(self._word_through(r, c, False, new)[2]) < 2
        elif len(rows) == 1:
            horizontal = True
        elif len(cols) == 1:
            horizontal = False
        else:
            res.errors.append("Brickorna ligger inte på en rad")
            return res

        p0 = placements[0]
        sr, sc, main_cells = self._word_through(p0.row, p0.col, horizontal, new)
        if sum(1 for cell in main_cells if cell[3]) != len(placements):
            res.errors.append("Det finns luckor mellan brickorna")
            return res

        words = []
        if len(main_cells) >= 2:
            text, s = self._score_cells(main_cells)
            words.append(Word(text, sr, sc, horizontal, s))
        for p in placements:
            cr, cc, cells = self._word_through(p.row, p.col, not horizontal, new)
            if len(cells) >= 2:
                text, s = self._score_cells(cells)
                words.append(Word(text, cr, cc, not horizontal, s))

        if self.is_empty_board():
            if (self.rules.start[0], self.rules.start[1]) not in new:
                res.errors.append("Första draget måste täcka startrutan")
            if len(placements) < 2:
                res.errors.append("Första ordet måste ha minst två bokstäver")
        else:
            touches = any(not cell[3] for cell in main_cells) or len(words) > 1
            if not touches:
                res.errors.append("Ordet ansluter inte till brickor på brädet")
        if not words:
            res.errors.append("Inget ord bildas")

        res.words = words
        res.score = sum(w.score for w in words)
        if len(placements) == self.rules.bingo_tiles:
            res.bingo = True
            res.score += self.rules.bingo_bonus
        return res


def rack_after(rack: str, placements) -> str:
    """Brickor kvar på hand efter att placeringarna lagts. Kastar ValueError om handen inte räcker."""
    left = list(rack)
    for p in placements:
        tile = BLANK if p.blank else p.letter
        if tile not in left:
            raise ValueError(f"Handen saknar {tile}")
        left.remove(tile)
    return "".join(left)
