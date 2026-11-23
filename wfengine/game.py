"""Matchtillstånd och lagring som JSON i games/."""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from itertools import combinations
from datetime import datetime
from pathlib import Path

from .board import Board, Placement
from .dictionary import MODES, NORMAL
from .rules import BLANK, Rules, check_bonus_counts, update_pass_count, validate_layout
from .tiles import TileCountError, bag_count, unseen_tiles

DEFAULT_GAMES_DIR = Path(__file__).resolve().parent.parent / "games"
PLAYERS = ("me", "opp")
FORMAT_VERSION = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class LogEntry:
    player: str                     # "me" / "opp"
    kind: str                       # "play" / "pass" / "exchange"
    score: int = 0
    word: str = ""
    row: int = -1
    col: int = -1
    horizontal: bool = True
    placements: list = field(default_factory=list)   # [{row, col, letter, blank}]
    count: int = 0                  # antal bytta brickor (vid byte)
    # För ångra:
    rack_before: str = ""
    scores_before: dict = field(default_factory=dict)
    passes_before: int = 0
    time: str = ""


@dataclass
class Game:
    id: str
    name: str
    layout: list[str]
    opponent: str = ""
    dict_mode: str = NORMAL
    starter: str = "me"             # vem som gör första draget
    turn: str = ""                  # vems tur det är ("" = härled från loggen)
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    tiles: list[dict] = field(default_factory=list)  # [{row, col, letter, blank}]
    rack: str = ""
    scores: dict = field(default_factory=lambda: {"me": 0, "opp": 0})
    consecutive_passes: int = 0
    log: list[LogEntry] = field(default_factory=list)

    # --- skapa / serialisera ----------------------------------------------
    @classmethod
    def new(cls, rules: Rules, name: str, layout=None, opponent: str = "", dict_mode: str = NORMAL,
            starter: str = "me") -> "Game":
        if starter not in PLAYERS:
            raise ValueError(f"Okänd spelare: {starter}")
        layout = list(layout) if layout is not None else list(rules.standard_layout)
        validate_layout(layout, rules.size)
        check_bonus_counts(layout, rules)
        if dict_mode not in MODES:
            raise ValueError(f"Okänt ordlisteläge: {dict_mode}")
        slug = re.sub(r"[^a-z0-9åäö]+", "-", name.lower()).strip("-")[:30] or "match"
        gid = f"{datetime.now():%Y%m%d-%H%M%S}-{slug}-{uuid.uuid4().hex[:4]}"
        return cls(id=gid, name=name.strip() or "Match", layout=layout, opponent=opponent,
                   dict_mode=dict_mode, starter=starter)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["version"] = FORMAT_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        d = dict(d)
        d.pop("version", None)
        d["log"] = [LogEntry(**e) for e in d.get("log", [])]
        return cls(**d)

    # --- härledda värden ---------------------------------------------------
    def board(self, rules: Rules) -> Board:
        b = Board(rules, self.layout)
        b.apply(Placement(t["row"], t["col"], t["letter"], t["blank"]) for t in self.tiles)
        return b

    def tile_status(self, rules: Rules) -> dict:
        """Osedda brickor och påse, eller felmeddelande om något är felinmatat."""
        try:
            unseen = unseen_tiles(rules, self.board(rules), self.rack)
        except TileCountError as e:
            return {"error": str(e), "unseen": {}, "unseen_count": None, "bag": None}
        except ValueError as e:
            return {"error": str(e), "unseen": {}, "unseen_count": None, "bag": None}
        return {"error": None, "unseen": dict(sorted(unseen.items())),
                "unseen_count": sum(unseen.values()), "bag": bag_count(rules, unseen)}

    # --- ändringar ---------------------------------------------------------
    @property
    def to_move(self) -> str:
        """Vems tur det är. Sparas efter varje drag och ångra; för äldre matchfiler
        utan sparad tur härleds den från loggen."""
        if self.turn in PLAYERS:
            return self.turn
        if self.log:
            return "opp" if self.log[-1].player == "me" else "me"
        return self.starter if self.starter in PLAYERS else "me"

    def check_turn(self, player: str) -> None:
        if player not in PLAYERS:
            raise ValueError(f"Okänd spelare: {player}")
        if player != self.to_move:
            who = "din" if self.to_move == "me" else "motståndarens"
            raise ValueError(f"Det är {who} tur. Ångra senaste draget om något blev fel.")

    def _entry(self, player: str, kind: str, **kw) -> LogEntry:
        self.check_turn(player)
        return LogEntry(player=player, kind=kind, rack_before=self.rack,
                        scores_before=dict(self.scores), passes_before=self.consecutive_passes,
                        time=_now(), **kw)

    def play(self, rules: Rules, player: str, placements, score: int, word: str,
             row: int, col: int, horizontal: bool) -> list[str]:
        """Lägger brickor. För 'me' tas brickorna ur handen. Ger varningar."""
        placements = list(placements)
        entry = self._entry(player, "play", score=score, word=word, row=row, col=col,
                            horizontal=horizontal,
                            placements=[asdict(p) for p in placements])
        warnings = []
        b = self.board(rules)
        b.apply(placements)  # kastar om en ruta är upptagen
        if player == "me":
            rack = list(self.rack)
            missing = []
            for p in placements:
                t = BLANK if p.blank else p.letter
                if t in rack:
                    rack.remove(t)
                else:
                    missing.append(t)
            if missing and self.rack:
                warnings.append(f"Handen saknade: {''.join(missing)}")
            self.rack = "".join(rack)
        self.tiles.extend(asdict(p) for p in placements)
        self.scores[player] += score
        self.consecutive_passes = update_pass_count(rules, self.consecutive_passes, "play")
        self.log.append(entry)
        self.turn = "opp" if player == "me" else "me"
        return warnings

    def pass_turn(self, rules: Rules, player: str) -> None:
        self.log.append(self._entry(player, "pass"))
        self.turn = "opp" if player == "me" else "me"
        self.consecutive_passes = update_pass_count(rules, self.consecutive_passes, "pass")

    def exchange(self, rules: Rules, player: str, tiles: str = "", count: int | None = None) -> None:
        """Byte. Egna byten kräver vilka brickor (tas ur handen, nya fylls i
        efteråt). Motståndarens byten kräver bara antal."""
        self.check_turn(player)
        tiles = tiles.strip().upper()
        if player == "me":
            if not tiles:
                raise ValueError("Välj vilka brickor du byter")
            rack = list(self.rack)
            for t in tiles:
                if t not in rack:
                    raise ValueError(f"Du har inte {t} på hand")
                rack.remove(t)
            count = len(tiles)
        else:
            count = len(tiles) if tiles else count
            if not count or not 1 <= count <= rules.rack_size:
                raise ValueError(f"Ange hur många brickor som byts (1–{rules.rack_size})")
        entry = self._entry(player, "exchange", word=tiles, count=count)
        if player == "me":
            self.rack = "".join(rack)
        self.log.append(entry)
        self.turn = "opp" if player == "me" else "me"
        self.consecutive_passes = update_pass_count(rules, self.consecutive_passes, "exchange")

    def undo(self) -> LogEntry | None:
        if not self.log:
            return None
        e = self.log.pop()
        self.turn = e.player            # turen går tillbaka till den vars drag ångrades
        if e.kind == "play":
            keys = {(p["row"], p["col"]) for p in e.placements}
            self.tiles = [t for t in self.tiles if (t["row"], t["col"]) not in keys]
        if e.player == "me":
            self.rack = e.rack_before
        self.scores = dict(e.scores_before)
        self.consecutive_passes = e.passes_before
        return e

    def game_over_reason(self, rules: Rules) -> str | None:
        n = rules.end_of_game["consecutive_passes_to_end"]
        if self.consecutive_passes >= n:
            return f"{n} pass i rad – matchen är slut"
        return None


# --- tolkning av inmatade ord ---------------------------------------------------

def interpret_word(board: Board, row: int, col: int, horizontal: bool, text: str,
                   rack: str = "") -> str:
    """Bestämmer vilka bokstäver som är blanka (gemen) i ett inmatat ord.

    - Blandat skiftläge (t.ex. "HUSet"): explicit, gemen = blank.
    - Enhetligt skiftläge ("drink"/"DRINK"): vanliga brickor. Om en hand anges
      används blank bara för bokstäver som saknas i handen, och blanken läggs
      där den ger högst poäng för draget.
    """
    text = text.strip()
    if any(c.isupper() for c in text) and any(c.islower() for c in text):
        return text
    up = text.upper()
    if not rack:
        return up
    dr, dc = (0, 1) if horizontal else (1, 0)
    new_idx = [i for i in range(len(up))
               if board.in_bounds(row + dr * i, col + dc * i) and not board.occupied(row + dr * i, col + dc * i)]
    avail = Counter(rack)
    need = Counter(up[i] for i in new_idx)
    shortage = Counter({ch: n - avail[ch] for ch, n in need.items() if n > avail[ch]})
    n_short = sum(shortage.values())
    if n_short == 0 or n_short > avail[BLANK]:
        return up   # inget behov av blank, eller handen räcker inte ändå (varnas på annat håll)

    def with_blanks(idx_set):
        return "".join(ch.lower() if i in idx_set else ch for i, ch in enumerate(up))

    best, best_score = None, None
    candidates = [i for i in new_idx if up[i] in shortage]
    for combo in combinations(candidates, n_short):
        if Counter(up[i] for i in combo) != shortage:
            continue
        cand = with_blanks(set(combo))
        try:
            score = board.evaluate(board.placements_for_word(row, col, horizontal, cand)).score
        except ValueError:
            return up
        if best_score is None or score > best_score:
            best, best_score = cand, score
    return best or up


# --- lagring -------------------------------------------------------------------

class GameStore:
    def __init__(self, directory: str | Path = DEFAULT_GAMES_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, gid: str) -> Path:
        if not re.fullmatch(r"[\w\-åäö]+", gid):
            raise ValueError("Ogiltigt match-id")
        return self.dir / f"{gid}.json"

    def save(self, game: Game) -> None:
        game.updated = _now()
        path = self._path(game.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(game.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def load(self, gid: str) -> Game:
        path = self._path(gid)
        if not path.exists():
            raise KeyError(gid)
        return Game.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def delete(self, gid: str) -> None:
        self._path(gid).unlink(missing_ok=True)

    def list(self) -> list[dict]:
        out = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({"id": d["id"], "name": d["name"], "opponent": d.get("opponent", ""),
                        "created": d["created"], "updated": d["updated"], "scores": d["scores"],
                        "dict_mode": d.get("dict_mode", NORMAL), "moves": len(d.get("log", []))})
        return sorted(out, key=lambda g: g["updated"], reverse=True)
