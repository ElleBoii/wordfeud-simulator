import random
from collections import Counter

import pytest

from wfengine import Board, Dictionary, unseen_tiles
from wfengine.evaluation import LeaveModel, WinModel, load_sim_config
from wfengine.movegen import Move
from wfengine.sim import (HUMAN, PERFECT, CandidateStats, SimContext, choose, deal, prune, rollout,
                          select_candidates)
from wfengine.simrunner import Simulation, SimSettings, WorkerPool

from conftest import TEST_WORDS


@pytest.fixture(scope="module")
def cfg():
    return load_sim_config()


@pytest.fixture
def models(cfg, rules):
    return LeaveModel(cfg["leave"], rules), WinModel(cfg["winmodel"], rules)


def board_with(rules, *words):
    b = Board(rules)
    for r, c, h, w in words:
        b.apply(b.placements_for_word(r, c, h, w))
    return b


def make_ctx(rules, cfg, board, rack, unseen=None, scores=(0, 0), passes=0, plies=2,
             model=PERFECT, seed=1):
    if unseen is None:
        unseen = unseen_tiles(rules, board, rack)
    unseen = tuple(sorted(Counter(unseen).elements()))
    return SimContext(rules=rules, layout=board.layout,
                      tiles=tuple((r, c, t.letter, t.blank) for r, c, t in board.tiles()),
                      rack=rack, unseen=unseen, scores=scores, passes=passes,
                      leave_cfg=cfg["leave"], win_cfg=cfg["winmodel"], opponent_model=model,
                      plies=plies, seed=seed)


# --- leave och vinstmodell ------------------------------------------------------

def test_leave_heuristic(models):
    leave, _ = models
    assert leave.value("") == 0
    assert leave.value("?") > leave.value("S") > leave.value("C")
    assert leave.value("EE") < 2 * leave.value("E")              # dubblettstraff
    assert leave.value("AEIOU") < leave.value("AERST")           # vokalobalans
    assert leave.value("RSTE") == leave.value("ETSR")            # ordningen spelar ingen roll
    assert leave.value("XE", bag_empty=True) == -(8 + 1)         # tom påse: brickpoäng räknas emot


def test_leave_table_overrides(cfg, rules):
    leave = LeaveModel(cfg["leave"], rules, table={"ERS": 42.0})
    assert leave.value("SRE") == 42.0
    assert leave.value("ER") != 42.0


def test_win_model(models):
    _, win = models
    assert win.win_prob(0, 50, True) > 0.5 > win.win_prob(0, 50, False)
    assert win.win_prob(30, 80, True) < win.win_prob(30, 10, True)   # σ krymper mot slutet
    assert win.win_prob(-200, 50, True) < 0.01
    assert win.sigma(0) == win.sigma_min


# --- dragning och policy ----------------------------------------------------------

def test_deal_is_deterministic_and_conserves_tiles(rules, cfg):
    b = board_with(rules, (7, 6, True, "HUS"))
    ctx = make_ctx(rules, cfg, b, "TAREN?S")
    opp, bag = deal(ctx, 3)
    assert (opp, bag) == deal(ctx, 3)
    assert deal(ctx, 4) != (opp, bag)
    assert len(opp) == 7
    assert Counter(opp) + Counter(bag) == Counter(ctx.unseen)


def test_choose_perfect_and_human(rules, small_dict, models):
    leave, _ = models
    b = board_with(rules, (7, 6, True, "HUS"))
    best = choose(b, "TARESNL", 50, small_dict, leave, rules, PERFECT)
    rng = random.Random(0)
    picks = {choose(b, "TARESNL", 50, small_dict, leave, rules, HUMAN, rng, top_n=5, temperature=5).value
             for _ in range(40)}
    assert best.value == max(picks)
    assert len(picks) > 1, "mänsklig modell ska ibland välja annat än bästa draget"
    assert choose(b, "", 0, small_dict, leave, rules).kind == "pass"


def test_select_candidates(rules, small_dict, models):
    leave, _ = models
    b = board_with(rules, (7, 6, True, "HUS"))
    c = select_candidates(b, "TARESNL", 50, small_dict, leave, 5)
    kinds = [m.kind for m, _ in c]
    assert kinds.count("play") == 5 and kinds.count("exchange") == 3 and kinds[-1] == "pass"
    plays = [v for m, v in c if m.kind == "play"]
    assert plays == sorted(plays, reverse=True)
    c2 = select_candidates(b, "TARESNL", 6, small_dict, leave, 5)
    assert not any(m.kind == "exchange" for m, _ in c2)
    for m, _ in c:
        if m.kind == "play":
            assert b.evaluate(m.placements).score == m.score


# --- rollout ----------------------------------------------------------------------

def test_rollout_deterministic(rules, cfg, small_dict, models):
    leave, win = models
    b = board_with(rules, (7, 6, True, "HUS"))
    ctx = make_ctx(rules, cfg, b, "TARESNL", scores=(20, 10), plies=3, model=HUMAN)
    cand = select_candidates(b, ctx.rack, 50, small_dict, leave, 3)[0][0]
    r1 = [rollout(ctx, cand, i, small_dict, leave, win) for i in range(5)]
    r2 = [rollout(ctx, cand, i, small_dict, leave, win) for i in range(5)]
    assert r1 == r2
    assert all(0.0 <= w <= 1.0 for w, _ in r1)


def test_rollout_three_passes_ends_game(rules, cfg, small_dict, models):
    leave, win = models
    b = board_with(rules, (7, 6, True, "HUS"))
    ctx = make_ctx(rules, cfg, b, "XC", scores=(30, 10), passes=2)
    w, m = rollout(ctx, Move("pass", leave="XC"), 0, small_dict, leave, win)
    opp, _ = deal(ctx, 0)
    opp_val = sum(rules.values[ch] for ch in opp)
    assert m == (30 - 16) - (10 - opp_val)
    assert w == (1.0 if m > 0 else 0.5 if m == 0 else 0.0)


def test_rollout_going_out_is_exact(rules, cfg, small_dict, models):
    leave, win = models
    b = board_with(rules, (7, 6, True, "HUS"))
    # Påsen är tom: motståndaren har exakt de osedda brickorna.
    ctx = make_ctx(rules, cfg, b, "ET", unseen="XC", scores=(5, 40))
    plays = [m for m, _ in select_candidates(b, "ET", 0, small_dict, leave, 50, include_pass=False)
             if len(m.placements) == 2]
    assert plays
    m0 = plays[0]
    w, m = rollout(ctx, m0, 0, small_dict, leave, win)
    assert m == (5 + m0.score + 16) - (40 - 16)
    assert w == (1.0 if m > 0 else 0.5 if m == 0 else 0.0)


# --- statistik och körning -----------------------------------------------------------

def test_prune_paired():
    good, bad, close = CandidateStats(), CandidateStats(), CandidateStats()
    rng = random.Random(1)
    for i in range(40):
        x = rng.random()
        good.add(i, 0.6 + 0.3 * x, 10)
        bad.add(i, 0.2 + 0.3 * x, 0)
        close.add(i, 0.6 + 0.3 * x - (0.01 if i % 2 else -0.01), 10)
    stats = [good, bad, close]
    assert prune(stats, "win", min_n=30) == [1]
    assert bad.pruned and not close.pruned and not good.pruned


def test_simulation_inline(rules, cfg, small_dict, models):
    leave, _ = models
    b = board_with(rules, (7, 6, True, "HUS"))
    ctx = make_ctx(rules, cfg, b, "TARESNL", scores=(8, 0))
    cands = select_candidates(b, ctx.rack, 90, small_dict, leave, 4)
    sim = Simulation(ctx, cands, SimSettings(iterations=6, prune=False))
    sim.run_inline(small_dict)
    snap = sim.snapshot()
    assert snap["status"] == "done", snap["error"]
    assert all(r["n"] == 6 for r in snap["candidates"])
    wins = [r["win"] for r in snap["candidates"]]
    assert wins == sorted(wins, reverse=True)
    assert snap["rollouts"] == 6 * len(cands)


def test_simulation_stops(rules, cfg, small_dict, models):
    leave, _ = models
    b = board_with(rules, (7, 6, True, "HUS"))
    ctx = make_ctx(rules, cfg, b, "TARESNL")
    cands = select_candidates(b, ctx.rack, 90, small_dict, leave, 3)
    sim = Simulation(ctx, cands, SimSettings(iterations=None, max_seconds=0.3))
    sim.run_inline(small_dict)
    assert sim.status == "done" and sim.elapsed() < 5 and sim.time_limited
    sim2 = Simulation(ctx, cands, SimSettings(iterations=None, max_seconds=60))
    sim2.stop()
    sim2.run_inline(small_dict)
    assert sim2.status == "stopped" and sim2.rollouts == 0


def test_pool_gives_same_result_as_inline(rules, cfg, tmp_path):
    """Processpoolen ska ge exakt samma rollouts som körning i en process (fast seed)."""
    (tmp_path / "words.txt").write_text("\n".join(TEST_WORDS), encoding="utf-8")
    d = Dictionary.load(rules.alphabet, tmp_path, mode="normal")
    leave = LeaveModel(cfg["leave"], rules)
    b = board_with(rules, (7, 6, True, "HUS"))
    ctx = make_ctx(rules, cfg, b, "TARE?NL", plies=2, model=HUMAN, seed=7)
    cands = select_candidates(b, ctx.rack, 90, d, leave, 3)
    settings = SimSettings(iterations=3, prune=False)

    inline = Simulation(ctx, cands, settings)
    inline.run_inline(d)
    pool = WorkerPool(rules.alphabet, tmp_path, 2)
    try:
        pooled = Simulation(ctx, cands, settings, job_key="t")
        pooled.run_pool(pool, "normal", ("x",))
    finally:
        pool.shutdown()
    assert pooled.status == "done", pooled.error
    assert [s.values for s in pooled.stats] == [s.values for s in inline.stats]


def test_rollout_to_the_end_is_exact(rules, cfg, small_dict, models):
    """plies = 0 (till slutet): med få brickor kvar tar matchen slut i rolluten."""
    leave, win = models
    b = board_with(rules, (7, 6, True, "HUS"), (6, 8, False, "OST"))
    ctx = make_ctx(rules, cfg, b, "TARE", unseen="ATSL", plies=0)
    for m, _ in select_candidates(b, ctx.rack, 0, small_dict, leave, 5):
        for it in range(3):
            w, _ = rollout(ctx, m, it, small_dict, leave, win)
            assert w in (0.0, 0.5, 1.0)
