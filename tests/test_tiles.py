import pytest

from wfengine import Board, TileCountError, bag_count, opponent_rack_size, unseen_tiles


def test_unseen_initial(rules):
    b = Board(rules)
    u = unseen_tiles(rules, b, "")
    assert sum(u.values()) == rules.total_tiles
    assert bag_count(rules, u) == rules.total_tiles - 7


def test_unseen_subtracts_board_and_rack(rules):
    b = Board(rules)
    b.apply(b.placements_for_word(7, 6, True, "HuS"))   # u = blank
    u = unseen_tiles(rules, b, "HA?")
    assert u["H"] == rules.counts["H"] - 2
    assert u["U"] == rules.counts["U"]
    assert u["?"] == rules.counts["?"] - 2
    assert u["S"] == rules.counts["S"] - 1
    assert "?" not in u or u["?"] == 0


def test_unseen_excess_error(rules):
    b = Board(rules)
    b.apply(b.placements_for_word(7, 7, True, "CC"))   # bara 1 C finns
    with pytest.raises(TileCountError) as e:
        unseen_tiles(rules, b, "")
    assert e.value.excess == {"C": 1}
    with pytest.raises(TileCountError):
        unseen_tiles(rules, Board(rules), "???")


def test_bag_near_end(rules):
    from collections import Counter
    assert bag_count(rules, Counter({"A": 5})) == 0
    assert opponent_rack_size(rules, Counter({"A": 5})) == 5
    assert bag_count(rules, Counter({"A": 9})) == 2


def test_tile_values_from_spec(rules):
    spec = {"A": 1, "B": 3, "C": 8, "D": 1, "E": 1, "F": 3, "G": 2, "H": 3, "I": 1, "J": 7,
            "K": 3, "L": 2, "M": 3, "N": 1, "O": 2, "P": 4, "R": 1, "S": 1, "T": 1, "U": 4,
            "V": 3, "X": 8, "Y": 7, "Z": 8, "Å": 4, "Ä": 4, "Ö": 4}
    assert {k: rules.values[k] for k in spec} == spec
    assert rules.counts["Q"] == rules.counts["W"] == 0
    assert sum(n for k, n in rules.counts.items() if k != "?") == 102


def test_pass_counting(rules):
    from wfengine.rules import is_game_over, update_pass_count
    n = 0
    for kind in ["pass", "pass", "exchange", "pass", "pass"]:
        n = update_pass_count(rules, n, kind)
    assert n == 2                      # byte nollställde
    assert not is_game_over(rules, n, 50, ["ABC", "DEF"])
    n = update_pass_count(rules, n, "pass")
    assert is_game_over(rules, n, 50, ["ABC", "DEF"])
    assert update_pass_count(rules, n, "play") == 0
    assert is_game_over(rules, 0, 0, ["", "DEF"])
    assert not is_game_over(rules, 0, 3, ["", "DEF"])


def test_final_adjustments(rules):
    from wfengine.rules import final_adjustments
    # Jag gick ut; motståndaren har C (8) + A (1) kvar.
    assert final_adjustments(rules, ["", "CA"]) == [9, -9]
    # Matchen slutade på pass: båda tappar sina egna.
    assert final_adjustments(rules, ["ZA", "?E"]) == [-9, -1]
