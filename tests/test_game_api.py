import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from wfengine.game import Game, GameStore

from conftest import TEST_WORDS


@pytest.fixture
def client(tmp_path):
    ddir = tmp_path / "dict"
    ddir.mkdir()
    (ddir / "words.txt").write_text("\n".join(TEST_WORDS), encoding="utf-8")
    (ddir / "words_strict.txt").write_text("HUS\nSOL\nTA\n", encoding="utf-8")
    app = create_app(games_dir=tmp_path / "games", dict_dir=ddir)
    return TestClient(app)


def new_game(client, **kw):
    r = client.post("/api/games", json={"name": "Test", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_store_roundtrip(tmp_path, rules):
    store = GameStore(tmp_path)
    g = Game.new(rules, "Kalle")
    b = g.board(rules)
    pl = b.placements_for_word(7, 6, True, "HuS")
    g.rack = "HS?ABC"
    g.play(rules, "me", pl, 7, "HuS", 7, 6, True)
    store.save(g)
    g2 = store.load(g.id)
    assert g2.tiles == g.tiles and g2.rack == "ABC" and g2.scores == {"me": 7, "opp": 0}
    assert [x["id"] for x in store.list()] == [g.id]
    assert g2.board(rules).get(7, 7).blank


def test_create_and_list(client):
    g = new_game(client, opponent="Kalle")
    assert g["layout"][0][0] == "t"
    games = client.get("/api/games").json()
    assert games[0]["id"] == g["id"] and games[0]["opponent"] == "Kalle"
    assert client.get(f"/api/games/{g['id']}").json()["tile_status"]["bag"] == 104 - 7


def test_custom_layout_validated(client):
    r = client.post("/api/games", json={"name": "x", "layout": ["." * 15] * 14})
    assert r.status_code == 400


def test_preview_and_play(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "hus?abc"})
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS"}).json()
    assert p["score"] == 8 and p["warnings"] == [] and p["words"][0]["valid"]

    r = client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "me"}).json()
    g = r["game"]
    assert g["scores"]["me"] == 8 and g["rack"] == "?ABC" and len(g["tiles"]) == 3

    # Motståndaren lägger ett ord som inte finns och inte ansluter: varning men tillåtet.
    p = client.post(f"/api/games/{gid}/preview", json={"row": 0, "col": 0, "horizontal": True, "word": "XQ"}).json()
    assert any("ansluter inte" in w for w in p["warnings"])
    assert any("inte i ordlistan" in w for w in p["warnings"])
    r = client.post(f"/api/games/{gid}/play", json={"row": 0, "col": 0, "horizontal": True, "word": "XQ", "player": "opp"})
    assert r.status_code == 200
    assert r.json()["game"]["rack"] == "?ABC"   # motståndarens drag påverkar inte min hand


def test_play_on_occupied_square_is_error(client):
    gid = new_game(client, starter="opp")["id"]
    client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "opp"})
    r = client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HAT", "player": "me"})
    assert r.status_code == 400


def test_undo_restores_everything(client):
    gid = new_game(client, starter="opp")["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "HUSABC?"})
    client.post(f"/api/games/{gid}/pass", json={"player": "opp"})
    client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "me"})
    g = client.post(f"/api/games/{gid}/undo").json()
    assert g["tiles"] == [] and g["rack"] == "HUSABC?" and g["scores"]["me"] == 0
    assert g["consecutive_passes"] == 1
    g = client.post(f"/api/games/{gid}/undo").json()
    assert g["consecutive_passes"] == 0
    assert client.post(f"/api/games/{gid}/undo").status_code == 400


def test_passes_end_game_and_exchange_resets(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "ABC"})
    for p in ["me", "opp"]:
        client.post(f"/api/games/{gid}/pass", json={"player": p})
    g = client.post(f"/api/games/{gid}/exchange", json={"player": "me", "tiles": "A"}).json()
    assert g["consecutive_passes"] == 0 and g["game_over"] is None
    for p in ["opp", "me", "opp"]:
        g = client.post(f"/api/games/{gid}/pass", json={"player": p}).json()
    assert g["game_over"]


def test_tile_error_shown(client):
    gid = new_game(client, starter="opp")["id"]
    client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 7, "horizontal": True, "word": "CC", "player": "opp"})
    g = client.get(f"/api/games/{gid}").json()
    assert "överskrider" in g["tile_status"]["error"]


def test_rack_validation(client):
    gid = new_game(client)["id"]
    assert client.patch(f"/api/games/{gid}", json={"rack": "ABCDEFGH"}).status_code == 400
    assert client.patch(f"/api/games/{gid}", json={"rack": "AB1"}).status_code == 400
    assert client.patch(f"/api/games/{gid}", json={"rack": "åä?"}).json()["rack"] == "ÅÄ?"


def test_analyze_sorted_by_score(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "HUSETAB"})
    a = client.post(f"/api/games/{gid}/analyze", json={}).json()
    plays = [m for m in a["moves"] if m["kind"] == "play"]
    assert plays and [m["score"] for m in plays] == sorted((m["score"] for m in plays), reverse=True)
    assert any(m["kind"] == "exchange" for m in a["moves"])
    assert a["moves"][-1]["kind"] == "pass"
    # Lägg bästa draget via API:t, som gränssnittet gör.
    best = plays[0]
    r = client.post(f"/api/games/{gid}/play", json={**{k: best[k] for k in ("row", "col", "horizontal", "word")}, "player": "me"}).json()
    assert r["score"] == best["score"] and r["game"]["rack"] == best["leave"]


def test_strict_mode_and_dict_corrections(client):
    gid = new_game(client, dict_mode="strikt")["id"]
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 6, "horizontal": True, "word": "HUSET"}).json()
    assert not p["words"][0]["valid"]
    client.post("/api/dict/add", json={"word": "huset", "mode": "strikt"})
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 6, "horizontal": True, "word": "HUSET"}).json()
    assert p["words"][0]["valid"]
    assert client.get("/api/dict/check", params={"word": "huset", "mode": "normal"}).json()["valid"]
    client.post("/api/dict/remove", json={"word": "hus", "mode": "normal"})
    assert not client.get("/api/dict/check", params={"word": "hus", "mode": "strikt"}).json()["valid"]


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Wordfeud-motor" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_lowercase_word_is_not_blanks(client):
    # Buggrapport: "drink" med gemener blev fem blanka och 0 poäng.
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "KRDNHTI"})
    client.post("/api/dict/add", json={"word": "drink"})
    r = client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 5, "horizontal": True, "word": "drink", "player": "me"}).json()
    g = r["game"]
    assert r["score"] > 0
    assert not any(t["blank"] for t in g["tiles"])
    assert g["rack"] == "HT" and g["tile_status"]["error"] is None


def test_auto_blank_for_missing_letter(client):
    gid = new_game(client, layout=["." * 15] * 7 + ["......t........"] + ["." * 15] * 7)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "HS?ABCD"})
    # HUS: U saknas i handen -> blank som U.
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 6, "horizontal": True, "word": "hus"}).json()
    assert p["interpreted"] == "HuS" and p["blanks"] == ["U"]
    # ATT med ett T saknat helt: blanken ska INTE hamna på TL (7,6) utan på ett vanligt T.
    client.patch(f"/api/games/{gid}", json={"rack": "AT?BCDE"})
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 5, "horizontal": True, "word": "ATT"}).json()
    assert p["interpreted"] == "ATt"
    # Blandat skiftläge = explicit.
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 5, "horizontal": True, "word": "AtT"}).json()
    assert p["interpreted"] == "AtT"


def test_opponent_lowercase_is_plain(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "??"})
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 6, "horizontal": True, "word": "hus", "player": "opp"}).json()
    assert p["interpreted"] == "HUS" and p["score"] == 8


def test_rack_shortage_warning(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "ABC"})
    p = client.post(f"/api/games/{gid}/preview", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS"}).json()
    assert any("räcker inte" in w for w in p["warnings"])


def test_added_word_playable_immediately(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "XQZWABC"})
    body = {"row": 7, "col": 6, "horizontal": True, "word": "XQZ"}
    assert not client.post(f"/api/games/{gid}/preview", json=body).json()["words"][0]["valid"]
    client.post("/api/dict/add", json={"word": "xqz"})
    assert client.post(f"/api/games/{gid}/preview", json=body).json()["words"][0]["valid"]
    a = client.post(f"/api/games/{gid}/analyze", json={}).json()
    assert any(m["word"] == "XQZ" for m in a["moves"])
    client.post("/api/dict/remove", json={"word": "xqz"})
    assert not client.post(f"/api/games/{gid}/preview", json=body).json()["words"][0]["valid"]


def test_exchange_own_tiles(client):
    gid = new_game(client)["id"]
    # Utan hand / utan valda brickor går det inte.
    assert client.post(f"/api/games/{gid}/exchange", json={"player": "me"}).status_code == 400
    client.patch(f"/api/games/{gid}", json={"rack": "AAXC?QE"})
    assert client.post(f"/api/games/{gid}/exchange", json={"player": "me", "tiles": "ZZ"}).status_code == 400
    g = client.post(f"/api/games/{gid}/exchange", json={"player": "me", "tiles": "xcq"}).json()
    assert g["rack"] == "AA?E"
    e = g["log"][-1]
    assert e["kind"] == "exchange" and e["count"] == 3 and e["word"] == "XCQ"
    g = client.post(f"/api/games/{gid}/undo").json()
    assert g["rack"] == "AAXC?QE"


def test_exchange_opponent_count(client):
    gid = new_game(client, starter="opp")["id"]
    assert client.post(f"/api/games/{gid}/exchange", json={"player": "opp"}).status_code == 400
    assert client.post(f"/api/games/{gid}/exchange", json={"player": "opp", "count": 8}).status_code == 400
    client.patch(f"/api/games/{gid}", json={"rack": "ABC"})
    g = client.post(f"/api/games/{gid}/exchange", json={"player": "opp", "count": 6}).json()
    assert g["log"][-1]["count"] == 6 and g["rack"] == "ABC"   # min hand orörd


def test_exchange_requires_bag(client, rules):
    gid = new_game(client, starter="opp")["id"]
    # Fyll brädet med 91 brickor (växelvis) -> 104-91-7 = 6 i påsen.
    letters = [ch for ch, n in rules.counts.items() if ch != "?" for _ in range(n)]
    for r in range(7):
        row = "".join(letters[r * 13:(r + 1) * 13])
        client.post(f"/api/games/{gid}/play", json={"row": r, "col": 0, "horizontal": True, "word": row,
                                                    "player": "opp" if r % 2 == 0 else "me"})
    g = client.get(f"/api/games/{gid}").json()
    assert g["tile_status"]["bag"] == 6
    r = client.post(f"/api/games/{gid}/exchange", json={"player": "me", "tiles": "A"})
    assert r.status_code == 400 and "påsen" in r.json()["detail"]


def test_turn_order_enforced(client):
    g = new_game(client)
    gid = g["id"]
    assert g["to_move"] == "me"
    # Motståndaren kan inte lägga när det är min tur.
    r = client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "opp"})
    assert r.status_code == 400 and "din tur" in r.json()["detail"]
    r = client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "me"})
    assert r.json()["game"]["to_move"] == "opp"
    # Jag kan inte lägga, passa eller byta igen.
    for path, body in [("play", {"row": 8, "col": 6, "horizontal": True, "word": "AT"}),
                       ("pass", {}), ("exchange", {"tiles": "A"})]:
        r = client.post(f"/api/games/{gid}/{path}", json={**body, "player": "me"})
        assert r.status_code == 400 and "motståndarens tur" in r.json()["detail"], path
    g = client.post(f"/api/games/{gid}/pass", json={"player": "opp"}).json()
    assert g["to_move"] == "me"
    # Ångra ger tillbaka turen.
    assert client.post(f"/api/games/{gid}/undo").json()["to_move"] == "opp"
    assert client.post(f"/api/games/{gid}/undo").json()["to_move"] == "me"


def test_starter_choice(client):
    g = new_game(client, starter="opp")
    assert g["to_move"] == "opp"
    gid = g["id"]
    assert client.patch(f"/api/games/{gid}", json={"starter": "me"}).json()["to_move"] == "me"
    client.post(f"/api/games/{gid}/pass", json={"player": "me"})
    assert client.patch(f"/api/games/{gid}", json={"starter": "opp"}).status_code == 400


def test_old_game_file_without_starter(tmp_path, rules):
    from wfengine.game import Game
    g = Game.new(rules, "gammal")
    d = g.to_dict()
    del d["starter"]
    assert Game.from_dict(d).to_move == "me"


def test_undo_returns_turn_to_undone_player(client):
    gid = new_game(client)["id"]
    client.patch(f"/api/games/{gid}", json={"rack": "ABCDE"})
    client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "me"})
    client.post(f"/api/games/{gid}/exchange", json={"player": "opp", "count": 4})
    g = client.post(f"/api/games/{gid}/pass", json={"player": "me"}).json()
    assert g["to_move"] == "opp"
    for expected in ["me", "opp", "me"]:          # ångra pass (jag), byte (opp), HUS (jag)
        g = client.post(f"/api/games/{gid}/undo").json()
        assert g["to_move"] == expected
    # Efter ångra kan den spelaren göra om sitt drag direkt.
    r = client.post(f"/api/games/{gid}/play", json={"row": 7, "col": 6, "horizontal": True, "word": "HUS", "player": "me"})
    assert r.status_code == 200 and r.json()["game"]["to_move"] == "opp"


def test_undo_turn_in_legacy_game_with_irregular_log(tmp_path, rules):
    # Äldre matchfil (före turordning) där jag gjorde två drag i rad.
    from wfengine.game import Game
    g = Game.new(rules, "gammal")
    g.play(rules, "me", g.board(rules).placements_for_word(7, 6, True, "HUS"), 8, "HUS", 7, 6, True)
    d = g.to_dict()
    d.pop("turn"); d.pop("starter")
    d["log"].append({**d["log"][0], "word": "X", "placements": []})   # me igen
    g = Game.from_dict(d)
    g.undo()
    assert g.to_move == "me"   # turen till den vars drag ångrades, oavsett loggens ordning
