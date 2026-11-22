"""FastAPI-app: API för matcher, ordlista och analys + statiska webbfiler."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from wfengine import Dictionary, add_word, generate_moves, load_rules, rack_after, remove_word
from wfengine.dictionary import (ADDED_FILE, ADDED_STRICT_FILE, BASE_FILES, DEFAULT_DICT_DIR,
                                 MODES, REMOVED_FILE, REMOVED_STRICT_FILE)
from wfengine.game import PLAYERS, Game, GameStore, interpret_word

STATIC = Path(__file__).resolve().parent / "static"


class DictCache:
    """Håller ordlistorna i minnet och laddar om när källfilerna ändras."""

    def __init__(self, alphabet: str, dict_dir: Path) -> None:
        self.alphabet, self.dir = alphabet, Path(dict_dir)
        self._cache: dict[str, tuple[tuple, Dictionary]] = {}
        self._lock = threading.Lock()

    def _stamp(self, mode: str) -> tuple:
        files = [BASE_FILES[mode], ADDED_FILE, REMOVED_FILE, ADDED_STRICT_FILE, REMOVED_STRICT_FILE]
        out = []
        for f in files:
            p = self.dir / f
            out.append(p.stat().st_mtime_ns if p.exists() else 0)
        return tuple(out)

    def base_exists(self, mode: str) -> bool:
        return (self.dir / BASE_FILES[mode]).exists()

    def get(self, mode: str) -> Dictionary:
        with self._lock:
            stamp = self._stamp(mode)
            hit = self._cache.get(mode)
            if hit is None or hit[0] != stamp:
                d = Dictionary.load(self.alphabet, self.dir, mode=mode)
                self._cache[mode] = (stamp, d)
                return d
            return hit[1]

    def apply_correction(self, word: str) -> None:
        """Uppdaterar inlästa ordlistor direkt efter en rättelse (utan ombyggnad)."""
        with self._lock:
            for mode, (_, d) in list(self._cache.items()):
                d.refresh_word(word)
                self._cache[mode] = (self._stamp(mode), d)

    def preload(self, mode: str = "normal") -> None:
        if self.base_exists(mode):
            threading.Thread(target=self.get, args=(mode,), daemon=True).start()


# --- förfrågningsmodeller ------------------------------------------------------

class NewGame(BaseModel):
    name: str
    opponent: str = ""
    starter: str = "me"
    layout: list[str] | None = None      # None = standardlayout
    dict_mode: str = "normal"


class WordInput(BaseModel):
    row: int
    col: int
    horizontal: bool = True
    word: str
    player: str = "me"


PlayInput = WordInput


class PlayerInput(BaseModel):
    player: str = "me"
    tiles: str = ""
    count: int | None = None


class GamePatch(BaseModel):
    name: str | None = None
    opponent: str | None = None
    rack: str | None = None
    scores: dict[str, int] | None = None
    consecutive_passes: int | None = None
    dict_mode: str | None = None
    starter: str | None = None


class AnalyzeInput(BaseModel):
    include_exchanges: bool = True
    include_pass: bool = True
    limit: int = 100


class DictWord(BaseModel):
    word: str
    mode: str = "normal"


def create_app(games_dir: str | Path | None = None, dict_dir: str | Path | None = None) -> FastAPI:
    rules = load_rules()
    store = GameStore(games_dir) if games_dir else GameStore()
    dict_dir = Path(dict_dir) if dict_dir else DEFAULT_DICT_DIR
    dicts = DictCache(rules.alphabet, dict_dir)
    dicts.preload()
    app = FastAPI(title="Wordfeud-motor")

    # --- hjälpfunktioner -----------------------------------------------------
    def get_game(gid: str) -> Game:
        try:
            return store.load(gid)
        except (KeyError, ValueError):
            raise HTTPException(404, "Matchen finns inte")

    def normalize_rack(rack: str) -> str:
        r = "".join(ch for ch in rack.strip().upper() if not ch.isspace())
        bad = [ch for ch in r if ch != "?" and ch not in rules.alphabet]
        if bad:
            raise HTTPException(400, f"Ogiltiga tecken i handen: {''.join(bad)}")
        if len(r) > rules.rack_size:
            raise HTTPException(400, f"Handen kan ha högst {rules.rack_size} brickor")
        return r

    def game_view(g: Game) -> dict:
        d = g.to_dict()
        d["tile_status"] = g.tile_status(rules)
        d["game_over"] = g.game_over_reason(rules)
        d["dict_missing"] = not dicts.base_exists(g.dict_mode)
        d["to_move"] = g.to_move
        return d

    def check_word(g: Game, w: WordInput) -> dict:
        """Placeringar, poäng, ord och varningar för ett inmatat ord."""
        board = g.board(rules)
        text = w.word.strip()
        if not text:
            raise HTTPException(400, "Skriv ett ord")
        bad = [ch for ch in text if ch.upper() not in rules.alphabet]
        if bad:
            raise HTTPException(400, f"Ogiltiga tecken: {''.join(bad)}")
        text = interpret_word(board, w.row, w.col, w.horizontal, text,
                              g.rack if w.player == "me" else "")
        try:
            placements = board.placements_for_word(w.row, w.col, w.horizontal, text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not placements:
            raise HTTPException(400, "Ordet lägger inga nya brickor")
        res = board.evaluate(placements)
        hard = [e for e in res.errors if "upptagen" in e or "utanför" in e]
        if hard:
            raise HTTPException(400, "; ".join(hard))
        d = dicts.get(g.dict_mode)
        words = [{"text": x.text, "valid": x.plain in d, "score": x.score} for x in res.words]
        warnings = list(res.errors)
        missing = [x["text"].upper() for x in words if not x["valid"]]
        if missing:
            warnings.append("Finns inte i ordlistan: " + ", ".join(missing))
        main = res.main_word
        blanks = [p.letter for p in placements if p.blank]
        if w.player == "me" and g.rack:
            try:
                rack_after(g.rack, placements)
            except ValueError:
                used = "".join("?" if p.blank else p.letter for p in placements)
                warnings.append(f"Din hand ({g.rack}) räcker inte till {used}")
        return {
            "interpreted": text, "blanks": blanks,
            "placements": [{"row": p.row, "col": p.col, "letter": p.letter, "blank": p.blank}
                           for p in placements],
            "_placements": placements,
            "score": res.score, "bingo": res.bingo, "words": words, "warnings": warnings,
            "word": main.text if main else text,
            "row": main.row if main else w.row, "col": main.col if main else w.col,
            "horizontal": main.horizontal if main else w.horizontal,
        }

    # --- regler / config -----------------------------------------------------
    @app.get("/api/config")
    def config():
        return {"alphabet": rules.alphabet, "values": rules.values, "counts": rules.counts,
                "size": rules.size, "start": rules.start, "rack_size": rules.rack_size,
                "standard_layout": rules.standard_layout, "unverified": rules.unverified,
                "dict_modes": MODES,
                "dict_available": {m: dicts.base_exists(m) for m in MODES}}

    # --- matcher ---------------------------------------------------------------
    @app.get("/api/games")
    def list_games():
        return store.list()

    @app.post("/api/games")
    def create_game(body: NewGame):
        try:
            g = Game.new(rules, body.name, body.layout, body.opponent, body.dict_mode, body.starter)
        except ValueError as e:
            raise HTTPException(400, str(e))
        store.save(g)
        return game_view(g)

    @app.get("/api/games/{gid}")
    def read_game(gid: str):
        return game_view(get_game(gid))

    @app.delete("/api/games/{gid}")
    def delete_game(gid: str):
        get_game(gid)
        store.delete(gid)
        return {"ok": True}

    @app.patch("/api/games/{gid}")
    def patch_game(gid: str, body: GamePatch):
        g = get_game(gid)
        if body.name is not None:
            g.name = body.name.strip() or g.name
        if body.opponent is not None:
            g.opponent = body.opponent.strip()
        if body.rack is not None:
            g.rack = normalize_rack(body.rack)
        if body.scores is not None:
            for k in PLAYERS:
                if k in body.scores:
                    g.scores[k] = int(body.scores[k])
        if body.consecutive_passes is not None:
            g.consecutive_passes = max(0, body.consecutive_passes)
        if body.starter is not None:
            if body.starter not in PLAYERS:
                raise HTTPException(400, "Okänd spelare")
            if g.log:
                raise HTTPException(400, "Vem som börjar kan bara ändras innan första draget")
            g.starter = body.starter
            g.turn = body.starter
        if body.dict_mode is not None:
            if body.dict_mode not in MODES:
                raise HTTPException(400, "Okänt ordlisteläge")
            g.dict_mode = body.dict_mode
        store.save(g)
        return game_view(g)

    @app.post("/api/games/{gid}/preview")
    def preview(gid: str, body: WordInput):
        info = check_word(get_game(gid), body)
        info.pop("_placements")
        return info

    @app.post("/api/games/{gid}/play")
    def play(gid: str, body: PlayInput):
        if body.player not in PLAYERS:
            raise HTTPException(400, "Okänd spelare")
        g = get_game(gid)
        try:
            g.check_turn(body.player)
        except ValueError as e:
            raise HTTPException(400, str(e))
        info = check_word(g, body)
        try:
            warnings = info["warnings"] + g.play(rules, body.player, info["_placements"], info["score"],
                                                 info["word"], info["row"], info["col"], info["horizontal"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        store.save(g)
        return {"game": game_view(g), "score": info["score"], "warnings": warnings}

    @app.post("/api/games/{gid}/pass")
    def pass_turn(gid: str, body: PlayerInput):
        if body.player not in PLAYERS:
            raise HTTPException(400, "Okänd spelare")
        g = get_game(gid)
        try:
            g.pass_turn(rules, body.player)
        except ValueError as e:
            raise HTTPException(400, str(e))
        store.save(g)
        return game_view(g)

    @app.post("/api/games/{gid}/exchange")
    def exchange(gid: str, body: PlayerInput):
        if body.player not in PLAYERS:
            raise HTTPException(400, "Okänd spelare")
        g = get_game(gid)
        try:
            g.check_turn(body.player)
        except ValueError as e:
            raise HTTPException(400, str(e))
        bag = g.tile_status(rules)["bag"]
        if bag is not None and bag < rules.exchange_min_bag:
            raise HTTPException(400, f"Byte är inte tillåtet: påsen har bara {bag} brickor "
                                     f"(minst {rules.exchange_min_bag} krävs)")
        try:
            g.exchange(rules, body.player, body.tiles, body.count)
        except ValueError as e:
            raise HTTPException(400, str(e))
        store.save(g)
        return game_view(g)

    @app.post("/api/games/{gid}/undo")
    def undo(gid: str):
        g = get_game(gid)
        if g.undo() is None:
            raise HTTPException(400, "Inget att ångra")
        store.save(g)
        return game_view(g)

    @app.post("/api/games/{gid}/analyze")
    def analyze(gid: str, body: AnalyzeInput):
        g = get_game(gid)
        if not g.rack:
            raise HTTPException(400, "Fyll i din hand först")
        status = g.tile_status(rules)
        d = dicts.get(g.dict_mode)
        board = g.board(rules)
        moves = generate_moves(board, g.rack, d, bag_count=status["bag"],
                               include_exchanges=body.include_exchanges,
                               include_pass=body.include_pass)
        plays = sorted((m for m in moves if m.kind == "play"),
                       key=lambda m: (-m.score, m.word))
        others = [m for m in moves if m.kind != "play"]
        out = []
        for m in plays[:max(1, body.limit)] + others:
            out.append({
                "kind": m.kind, "word": m.word, "row": m.row, "col": m.col,
                "horizontal": m.horizontal, "score": m.score, "leave": m.leave,
                "exchanged": m.exchanged, "label": m.describe(),
                "placements": [{"row": p.row, "col": p.col, "letter": p.letter, "blank": p.blank}
                               for p in m.placements],
            })
        notes = []
        if status["error"]:
            notes.append(status["error"])
        if body.include_exchanges and status["bag"] is not None and status["bag"] < rules.exchange_min_bag:
            notes.append(f"Byte inte tillåtet: bara {status['bag']} brickor i påsen")
        if not dicts.base_exists(g.dict_mode):
            notes.append("Ordlistan saknas – kör python scripts/fetch_saldo.py")
        return {"moves": out, "total_plays": len(plays), "notes": notes}

    # --- ordlista ---------------------------------------------------------------
    @app.get("/api/dict/check")
    def dict_check(word: str, mode: str = "normal"):
        if mode not in MODES:
            raise HTTPException(400, "Okänt ordlisteläge")
        return {"word": word.upper(), "valid": word.strip().upper() in dicts.get(mode)}

    @app.post("/api/dict/add")
    def dict_add(body: DictWord):
        try:
            w = add_word(body.word, rules.alphabet, dict_dir, mode=body.mode)
        except ValueError as e:
            raise HTTPException(400, str(e))
        dicts.apply_correction(w)
        return {"word": w, "ok": True}

    @app.post("/api/dict/remove")
    def dict_remove(body: DictWord):
        try:
            w = remove_word(body.word, rules.alphabet, dict_dir, mode=body.mode)
        except ValueError as e:
            raise HTTPException(400, str(e))
        dicts.apply_correction(w)
        return {"word": w, "ok": True}

    # --- webbfiler --------------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
