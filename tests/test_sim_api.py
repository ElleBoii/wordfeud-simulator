import time

import pytest
from fastapi.testclient import TestClient

from server.app import create_app

from conftest import TEST_WORDS


@pytest.fixture
def client(tmp_path):
    ddir = tmp_path / "dict"
    ddir.mkdir()
    (ddir / "words.txt").write_text("\n".join(TEST_WORDS), encoding="utf-8")
    (ddir / "words_strict.txt").write_text("HUS\nSOL\nTA\n", encoding="utf-8")
    app = create_app(games_dir=tmp_path / "games", dict_dir=ddir, sim_workers=1)
    with TestClient(app) as c:
        yield c


def new_game(client, **kw):
    g = client.post("/api/games", json={"name": "Sim", **kw}).json()
    return g["id"]


def wait_done(client, job, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        r = client.get(f"/api/sim/{job}").json()
        if r["status"] not in ("running", "pending"):
            return r
        time.sleep(0.05)
    raise AssertionError("simuleringen blev inte klar")


def test_settings_roundtrip(client, tmp_path):
    s = client.get("/api/settings").json()
    assert s["opponent_model"] == "perfect" and s["plies"] == 2
    s.update(plies=4, opponent_model="human", iterations=20)
    assert client.put("/api/settings", json=s).json()["plies"] == 4
    assert client.get("/api/settings").json()["opponent_model"] == "human"
    assert (tmp_path / "settings.json").exists()
    for bad in (9, 6, -1):
        assert client.put("/api/settings", json=dict(s, plies=bad)).status_code == 422
    assert client.put("/api/settings", json=dict(s, plies=0)).json()["plies"] == 0   # till slutet
    assert client.put("/api/settings", json=dict(s, plies=10)).json()["plies"] == 10


def test_simulate_runs_and_reports(client):
    gid = new_game(client)
    client.patch(f"/api/games/{gid}", json={"rack": "TARESNL"})
    s = client.get("/api/settings").json()
    s.update(iterations=5, candidates=4, prune=False)
    r = client.post(f"/api/games/{gid}/simulate", json={"settings": s})
    assert r.status_code == 200, r.text
    snap = wait_done(client, r.json()["job"])
    assert snap["status"] == "done", snap["error"]
    assert snap["target_iterations"] == 5 and r.json()["estimate"]["selected"]["max_iterations"] >= 5
    plays = [c for c in snap["candidates"] if c["kind"] == "play"]
    assert len(plays) == 4 and all(c["n"] == 5 for c in snap["candidates"])
    assert all(c["win"] is not None and 0 <= c["win"] <= 100 for c in snap["candidates"])
    assert any(c["kind"] == "pass" for c in snap["candidates"])
    # Ett simulerat drag ska gå att lägga via vanliga /play.
    best = plays[0]
    p = client.post(f"/api/games/{gid}/play", json={"row": best["row"], "col": best["col"],
                    "horizontal": best["horizontal"], "word": best["word"], "player": "me"})
    assert p.status_code == 200 and p.json()["score"] == best["score"]


def test_simulate_stop(client):
    gid = new_game(client)
    client.patch(f"/api/games/{gid}", json={"rack": "TARESNL"})
    s = client.get("/api/settings").json()
    s.update(iterations=0)
    job = client.post(f"/api/games/{gid}/simulate", json={"settings": s}).json()["job"]
    client.post(f"/api/sim/{job}/stop")
    assert wait_done(client, job)["status"] == "stopped"


def test_simulate_requires_my_turn_and_rack(client):
    gid = new_game(client, starter="opp")
    assert client.post(f"/api/games/{gid}/simulate", json={}).status_code == 400   # ingen hand
    client.patch(f"/api/games/{gid}", json={"rack": "TARESNL"})
    r = client.post(f"/api/games/{gid}/simulate", json={})
    assert r.status_code == 400 and "din tur" in r.json()["detail"]
    assert client.get("/api/sim/finnsinte").status_code == 404


def test_estimate_lists_all_options(client):
    gid = new_game(client)
    client.patch(f"/api/games/{gid}", json={"rack": "TARESNL"})
    est = client.get(f"/api/games/{gid}/estimate").json()
    assert [o["plies"] for o in est["options"]] == [1, 2, 3, 4, 5, 10, 0]
    assert all(o["feasible"] for o in est["options"])           # liten testordlista = snabbt
    its = [o["max_iterations"] for o in est["options"]]
    assert its[0] >= its[1] >= its[2] >= its[4] >= its[5]
    # Till slutet = lika många drag som uppskattas vara kvar i matchen (färre än 100).
    end = est["options"][-1]
    assert end["effective_plies"] == est["moves_left"] - 1


def test_simulation_refused_when_nothing_fits(client):
    gid = new_game(client)
    client.patch(f"/api/games/{gid}", json={"rack": "TARESNL"})
    client.app.state.sims.budget["cost_factor"] = 1e9            # simulera en extremt långsam dator
    r = client.post(f"/api/games/{gid}/simulate", json={})
    assert r.status_code == 400 and "ryms inte" in r.json()["detail"]
    est = client.get(f"/api/games/{gid}/estimate").json()
    assert not any(o["feasible"] for o in est["options"])


def test_iterations_capped_by_budget(client):
    gid = new_game(client)
    client.patch(f"/api/games/{gid}", json={"rack": "TARESNL"})
    s = client.get("/api/settings").json()
    s.update(iterations=100000, prune=False)
    client.app.state.sims.budget["max_iterations"] = 3
    r = client.post(f"/api/games/{gid}/simulate", json={"settings": s}).json()
    assert r["target_iterations"] == 3
    assert any("ryms inte" in n for n in r["notes"])
    assert wait_done(client, r["job"])["iterations"] == 3
