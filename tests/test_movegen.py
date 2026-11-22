import random
from collections import Counter
from itertools import product

import pytest

from wfengine import Board, Placement, generate_exchanges, generate_moves, generate_plays


def brute_force_plays(board, rack, dictionary):
    """Oberoende (långsam) generator: prova varje ord på varje position."""
    rack_c = Counter(rack)
    size = board.size
    out = {}
    # Snabbfilter: en läggning måste röra en bricka, en granne till en bricka eller startrutan.
    touch = [[board.occupied(r, c) or any(board.occupied(r + a, c + b) for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
              for c in range(size)] for r in range(size)]
    if board.is_empty_board():
        touch[board.rules.start[0]][board.rules.start[1]] = True
    for word in dictionary.words:
        n = len(word)
        for horizontal in (True, False):
            dr, dc = (0, 1) if horizontal else (1, 0)
            for r in range(size):
                for c in range(size):
                    er, ec = r + dr * (n - 1), c + dc * (n - 1)
                    if not board.in_bounds(er, ec):
                        continue
                    if board.occupied(r - dr, c - dc) or board.occupied(er + dr, ec + dc):
                        continue
                    if not any(touch[r + dr * i][c + dc * i] for i in range(n)):
                        continue
                    need, ok = [], True
                    for i, ch in enumerate(word):
                        t = board.get(r + dr * i, c + dc * i)
                        if t is None:
                            need.append((r + dr * i, c + dc * i, ch))
                        elif t.letter != ch:
                            ok = False
                            break
                    if not ok or not need:
                        continue
                    for blanks in product((False, True), repeat=len(need)):
                        use = Counter("?" if b else ch for (_, _, ch), b in zip(need, blanks))
                        if any(use[k] > rack_c[k] for k in use):
                            continue
                        pl = tuple(sorted(Placement(rr, cc, ch, b) for (rr, cc, ch), b in zip(need, blanks)))
                        if pl in out:
                            continue
                        res = board.evaluate(pl)
                        if res.ok and all(w.plain in dictionary for w in res.words):
                            out[pl] = res.score
    return out


def random_rack(rng, bag, k=7):
    rng.shuffle(bag)
    rack = "".join(bag[:k])
    del bag[:k]
    return rack


def full_bag(rules):
    return [ch for ch, n in rules.counts.items() for _ in range(n)]


def random_positions(rules, dictionary, seed, n_moves):
    """Spelar slumpmässiga lagliga drag och ger (bräde, hand) efter varje drag."""
    rng = random.Random(seed)
    board = Board(rules)
    bag = full_bag(rules)
    for _ in range(n_moves):
        rack = random_rack(rng, bag)
        yield board, rack
        plays = generate_plays(board, rack, dictionary)
        bag.extend(rack)
        if plays:
            board.apply(rng.choice(plays).placements)


def test_first_move_both_directions(rules, small_dict):
    b = Board(rules)
    plays = generate_plays(b, "HUSETXX", small_dict)
    words = {(m.word, m.horizontal) for m in plays}
    assert ("HUSET", True) in words and ("HUSET", False) in words
    for m in plays:
        assert any((p.row, p.col) == rules.start for p in m.placements)


def test_empty_rack_and_no_moves(rules, small_dict):
    b = Board(rules)
    assert generate_plays(b, "", small_dict) == []
    assert generate_plays(b, "XXQ", small_dict) == []


def test_blank_generates_all_letters(rules, small_dict):
    b = Board(rules)
    b.apply(b.placements_for_word(7, 6, True, "HUS"))
    plays = generate_plays(b, "?", small_dict)
    assert all(any(p.blank for p in m.placements) for m in plays)
    assert all(m.score >= 0 for m in plays)
    assert plays, "Blank borde kunna läggas någonstans"


def test_rack_with_letter_and_blank_gives_both_variants(rules, small_dict):
    b = Board(rules)
    plays = generate_plays(b, "AT?", small_dict)
    att = [m for m in plays if m.word.upper() == "ATT" and m.horizontal and m.col == 7]
    # A,T + blank som T i olika ordning: ATt, AtT är olika drag (olika rutor för blanken).
    assert {m.word for m in att} == {"ATt", "AtT"}


@pytest.mark.parametrize("seed", range(6))
def test_movegen_matches_brute_force(rules, small_dict, seed):
    for board, rack in random_positions(rules, small_dict, seed, 12):
        for r in (rack, rack[:5] + "?", rack[:3] + "??"):
            gen = {m.placements: m.score for m in generate_plays(board, r, small_dict)}
            brute = brute_force_plays(board, r, small_dict)
            assert gen == brute, f"seed={seed} rack={r}\n{board}"


def test_generated_moves_are_valid(rules, small_dict):
    for board, rack in random_positions(rules, small_dict, 99, 15):
        for m in generate_plays(board, rack, small_dict):
            res = board.evaluate(m.placements)
            assert res.ok
            assert all(w.plain in small_dict for w in res.words)
            assert res.score == m.score
            assert sorted(m.leave + "".join("?" if p.blank else p.letter for p in m.placements)) == sorted(rack)


def test_exchanges_unique_subsets():
    ex = generate_exchanges("AAB")
    assert sorted(m.exchanged for m in ex) == sorted(["A", "AA", "B", "AB", "AAB"])
    assert len(generate_exchanges("ABCDEFG")) == 2 ** 7 - 1
    assert len(generate_exchanges("AA??BBC")) == 3 * 3 * 3 * 2 - 1


def test_exchange_requires_bag(rules, small_dict):
    b = Board(rules)
    rack = "HUSETAB"
    with_ex = generate_moves(b, rack, small_dict, bag_count=rules.exchange_min_bag)
    without = generate_moves(b, rack, small_dict, bag_count=rules.exchange_min_bag - 1)
    assert any(m.kind == "exchange" for m in with_ex)
    assert not any(m.kind == "exchange" for m in without)
    assert sum(m.kind == "pass" for m in without) == 1
