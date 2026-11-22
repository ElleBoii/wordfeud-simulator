import pytest

from wfengine import Board, Placement, rack_after

# Poäng enligt config: H=3 U=4 S=1 E=1 T=1 A=1 R=1 O=2 N=1 Z=8


def layout_with(**squares):
    """Tom layout med bonusar på angivna rutor, t.ex. r7c7='D'."""
    grid = [["."] * 15 for _ in range(15)]
    for key, code in squares.items():
        r, c = key[1:].split("c")
        grid[int(r)][int(c)] = code
    return ["".join(row) for row in grid]


def play(board, row, col, horizontal, text):
    pl = board.placements_for_word(row, col, horizontal, text)
    res = board.evaluate(pl)
    assert res.ok, res.errors
    board.apply(pl)
    return res


def test_first_move_plain(rules):
    b = Board(rules, layout_with())
    res = play(b, 7, 6, True, "HUS")
    assert res.score == 3 + 4 + 1
    assert res.main_word.text == "HUS"


def test_first_move_must_cover_start(rules):
    b = Board(rules, layout_with())
    res = b.evaluate(b.placements_for_word(0, 0, True, "HUS"))
    assert "Första draget måste täcka startrutan" in res.errors


def test_letter_and_word_bonus(rules):
    b = Board(rules, layout_with(r7c6="t", r7c8="D"))
    res = play(b, 7, 6, True, "HUS")   # H på TL, S på DW
    assert res.score == (3 * 3 + 4 + 1) * 2


def test_two_word_multipliers_multiply(rules):
    b = Board(rules, layout_with(r7c5="T", r7c9="D"))
    res = play(b, 7, 5, True, "HUSET")
    assert res.score == (3 + 4 + 1 + 1 + 1) * 3 * 2


def test_bonus_only_for_new_tiles(rules):
    b = Board(rules, layout_with(r7c6="D", r7c7="t"))
    play(b, 7, 6, True, "HUS")
    res = play(b, 7, 6, True, "HUSET")   # förlänger; H och U ligger på bonusrutor men är gamla
    assert [p.col for p in res.placements] == [9, 10]
    assert res.score == 3 + 4 + 1 + 1 + 1


def test_extend_through_existing_tile_with_new_bonus(rules):
    b = Board(rules, layout_with(r8c8="D"))
    play(b, 7, 6, True, "HUS")           # H(7,6) U(7,7) S(7,8)
    res = play(b, 7, 8, False, "SET")    # E(8,8) på DW, T(9,8)
    assert res.main_word.text == "SET"
    assert res.score == (1 + 1 + 1) * 2


def test_cross_words_counted_with_shared_bonus(rules):
    b = Board(rules, layout_with(r8c7="t"))
    play(b, 7, 6, True, "HAT")           # H(7,6) A(7,7) T(7,8)
    res = b.evaluate([Placement(8, 7, "T"), Placement(8, 8, "A")])
    # Huvudord "TA" (rad 8), korsord "AT" (kolumn 7) och "TA" (kolumn 8).
    assert sorted(w.text for w in res.words) == ["AT", "TA", "TA"]
    # T(8,7) på TL räknas tredubbelt i båda orden den ingår i.
    assert res.score == (1 * 3 + 1) + (1 + 1 * 3) + (1 + 1)


def test_rules_page_example_zon(rules):
    # Från regelsidan: ZON med Z på TL och ordet över en DW ger 54 poäng.
    b = Board(rules, layout_with(r7c6="t", r7c8="D"))
    res = play(b, 7, 6, True, "ZON")
    assert res.score == 54


def test_blank_scores_zero(rules):
    b = Board(rules, layout_with(r7c6="t", r7c7="D"))
    res = play(b, 7, 6, True, "hUS")     # blank som H på TL
    assert res.score == (0 + 4 + 1) * 2
    assert res.main_word.text == "hUS"
    assert b.get(7, 6).blank and b.get(7, 6).letter == "H"


def test_existing_blank_scores_zero(rules):
    b = Board(rules, layout_with())
    play(b, 7, 6, True, "hUS")
    res = play(b, 7, 6, True, "hUSET")
    assert res.score == 0 + 4 + 1 + 1 + 1


def test_bingo_bonus(rules):
    b = Board(rules, layout_with())
    res = play(b, 7, 3, True, "STATARE")
    assert len(res.placements) == 7 and res.bingo
    assert res.score == 7 + rules.bingo_bonus


def test_six_tiles_no_bingo(rules):
    b = Board(rules, layout_with())
    res = play(b, 7, 4, True, "TALANG")
    assert not res.bingo


def test_geometry_errors(rules):
    b = Board(rules, layout_with())
    play(b, 7, 6, True, "HUS")
    # Inte på en rad
    res = b.evaluate([Placement(0, 0, "A"), Placement(1, 1, "B")])
    assert "Brickorna ligger inte på en rad" in res.errors
    # Lucka
    res = b.evaluate([Placement(9, 6, "A"), Placement(9, 8, "B")])
    assert "Det finns luckor mellan brickorna" in res.errors
    # Ansluter inte
    res = b.evaluate([Placement(0, 0, "A"), Placement(0, 1, "T")])
    assert "Ordet ansluter inte till brickor på brädet" in res.errors
    # Upptagen
    res = b.evaluate([Placement(7, 6, "A")])
    assert any("upptagen" in e for e in res.errors)
    # Lucka som fylls av en befintlig bricka är OK
    res = b.evaluate([Placement(6, 7, "N"), Placement(8, 7, "S")])  # N-U-S lodrätt
    assert res.ok and res.main_word.text == "NUS"


def test_single_tile_scores_both_directions(rules):
    b = Board(rules, layout_with(r8c8="d"))
    play(b, 7, 7, True, "AT")            # A(7,7) T(7,8)
    play(b, 8, 6, True, "TA")            # T(8,6) A(8,7); bildar "AA" lodrätt (ordlistan kontrolleras inte här)
    res = b.evaluate([Placement(8, 8, "S")])   # "TAS" vågrätt + "TS" lodrätt
    texts = sorted(w.text for w in res.words)
    assert texts == ["TAS", "TS"]
    assert res.score == (1 + 1 + 2) + (1 + 2)


def test_placements_for_word_checks_existing(rules):
    b = Board(rules, layout_with())
    play(b, 7, 6, True, "HUS")
    with pytest.raises(ValueError):
        b.placements_for_word(7, 6, True, "HAT")


def test_rack_after(rules):
    pl = [Placement(0, 0, "A"), Placement(0, 1, "B", blank=True)]
    assert rack_after("AC?", pl) == "C"
    with pytest.raises(ValueError):
        rack_after("AB", pl)
