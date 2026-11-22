"""Snabbtest med riktig ordlista: python scripts/demo.py [HAND] [normal|strikt]

Laddar dict/words.txt, lägger ett par ord på brädet och listar de bästa dragen
för given hand samt tidsåtgång.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wfengine import Board, Dictionary, generate_moves, load_rules, unseen_tiles, bag_count  # noqa: E402

rules = load_rules()
t = time.perf_counter()
mode = sys.argv[2] if len(sys.argv) > 2 else "normal"
d = Dictionary.load(rules.alphabet, mode=mode)
print(f"Ordlista ({mode}): {len(d):,} ord, laddad på {time.perf_counter() - t:.1f} s")
if rules.unverified:
    print("OBS: ej verifierade regelsektioner:", ", ".join(rules.unverified))

b = Board(rules)
for row, col, horiz, word in [(7, 5, True, "HUSET"), (5, 9, False, "KATTEN")]:
    pl = b.placements_for_word(row, col, horiz, word)
    res = b.evaluate(pl)
    print(f"Lägger {word}: {res.score} p, ord: {[w.text for w in res.words]}, "
          f"i ordlistan: {all(w.plain in d for w in res.words)}")
    b.apply(pl)
print(b)

rack = sys.argv[1] if len(sys.argv) > 1 else "ARSTL?E"
bag = bag_count(rules, unseen_tiles(rules, b, rack))
t = time.perf_counter()
moves = generate_moves(b, rack, d, bag_count=bag)
dt = time.perf_counter() - t
plays = sorted((m for m in moves if m.kind == "play"), key=lambda m: -m.score)
print(f"\nHand {rack}: {len(plays)} läggningar + {len(moves) - len(plays)} byten/pass på {dt * 1000:.0f} ms")
for m in plays[:15]:
    print(f"  {m.describe():30s} kvar: {m.leave}")
