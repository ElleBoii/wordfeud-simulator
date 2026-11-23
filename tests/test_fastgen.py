import pytest

from wfengine import Board, Placement, generate_plays
from wfengine.fastgen import scored_plays

from test_movegen import random_positions


def as_map(fast):
    out = {}
    for score, pl in fast:
        key = tuple(sorted(Placement(*p) for p in pl))
        assert key not in out, f"dubblett: {key}"
        out[key] = score
    return out


@pytest.mark.parametrize("seed", range(8))
def test_fastgen_matches_reference(rules, small_dict, seed):
    for board, rack in random_positions(rules, small_dict, seed, 14):
        for r in (rack, rack[:5] + "?", rack[:3] + "??", rack[:1]):
            ref = {m.placements: m.score for m in generate_plays(board, r, small_dict)}
            assert as_map(scored_plays(board, r, small_dict)) == ref, f"seed={seed} rack={r}\n{board}"


def test_fastgen_first_move_and_bingo(rules, small_dict):
    b = Board(rules)
    fast = as_map(scored_plays(b, "ATTRAPS", small_dict))
    ref = {m.placements: m.score for m in generate_plays(b, "ATTRAPS", small_dict)}
    assert fast == ref
    assert any(len(k) == 7 for k in fast), "ATTRAPS borde ge bingo"


def test_fastgen_empty_rack(rules, small_dict):
    assert scored_plays(Board(rules), "", small_dict) == []
