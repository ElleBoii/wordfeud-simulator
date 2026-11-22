from wfengine import Dictionary, add_word, remove_word
from wfengine.dictionary import build_dawg, normalize


def test_rules_load(rules):
    assert rules.size == 15
    assert len(rules.alphabet) == 29
    assert rules.counts["?"] == 2
    assert rules.values["?"] == 0
    assert rules.total_tiles == 104
    # Standardlayouten ska vara symmetrisk.
    lay = rules.standard_layout
    for r in range(15):
        for c in range(15):
            assert lay[r][c] == lay[c][r] == lay[14 - r][c] == lay[r][14 - c]
    assert rules.unverified == ()  # allt i config är verifierat


def test_normalize(rules):
    a = rules.alphabet
    assert normalize("hus", a) == "HUS"
    assert normalize("  Åsna\n", a) == "ÅSNA"
    assert normalize("a", a) is None            # för kort
    assert normalize("x" * 16, a) is None       # för långt
    assert normalize("ab-c", a) is None
    assert normalize("ab c", a) is None
    assert normalize("ab1", a) is None
    assert normalize("café", a) is None


def _walk(node, prefix=""):
    if node.final:
        yield prefix
    for ch, child in node.children.items():
        yield from _walk(child, prefix + ch)


def test_dawg_contains_exactly_words():
    words = {"HUS", "HUSET", "HUSEN", "BUS", "BUSEN", "BUSET", "AT", "ATT", "ÅT", "ÖL"}
    root = build_dawg(words)
    assert set(_walk(root)) == words


def test_dawg_is_minimized():
    # HUSET/BUSET och HUSEN/BUSEN delar suffix -> noden efter "HUS" och "BUS" är samma.
    root = build_dawg({"HUS", "HUSET", "HUSEN", "BUS", "BUSET", "BUSEN"})
    h = root.children["H"].children["U"].children["S"]
    b = root.children["B"].children["U"].children["S"]
    assert h is b


def test_load_with_corrections(tmp_path, rules):
    a = rules.alphabet
    (tmp_path / "words.txt").write_text("hus\nhuset\nbil\nx-ray\nö\nÖL\n", encoding="utf-8")
    d = Dictionary.load(a, tmp_path)
    assert set(d.words) == {"HUS", "HUSET", "BIL", "ÖL"}

    add_word("ost", a, tmp_path)
    remove_word("bil", a, tmp_path)
    d = Dictionary.load(a, tmp_path)
    assert "OST" in d and "BIL" not in d

    # Att lägga till ett borttaget ord flyttar det mellan filerna.
    add_word("bil", a, tmp_path)
    assert "BIL" not in (tmp_path / "removed.txt").read_text(encoding="utf-8")
    assert "BIL" in Dictionary.load(a, tmp_path)


def test_latin1_fallback(tmp_path, rules):
    (tmp_path / "words.txt").write_bytes("åsna\nöl\n".encode("latin-1"))
    d = Dictionary.load(rules.alphabet, tmp_path)
    assert set(d.words) == {"ÅSNA", "ÖL"}


def test_strict_mode(tmp_path, rules):
    a = rules.alphabet
    (tmp_path / "words.txt").write_text("hus\nhuset\nbil\nbilen\n", encoding="utf-8")
    (tmp_path / "words_strict.txt").write_text("hus\nbil\n", encoding="utf-8")
    assert set(Dictionary.load(a, tmp_path, mode="strikt").words) == {"HUS", "BIL"}

    # Godkänt i strikt läge -> giltigt i båda.
    add_word("ost", a, tmp_path, mode="strikt")
    # Nekat i strikt läge -> bara borta i strikt.
    remove_word("bil", a, tmp_path, mode="strikt")
    # Nekat i normalt läge -> borta i båda.
    remove_word("hus", a, tmp_path)
    normal = Dictionary.load(a, tmp_path)
    strict = Dictionary.load(a, tmp_path, mode="strikt")
    assert set(normal.words) == {"HUSET", "BIL", "BILEN", "OST"}
    assert set(strict.words) == {"OST"}
    assert strict.mode == "strikt"


def test_inplace_add_and_discard_do_not_leak():
    words = {"HUS", "HUSET", "BUS", "BUSET", "MUS"}
    d = Dictionary(words)
    old_root = d.root
    d.add("HUSETS")          # delad suffixnod med BUSET -> får inte ge BUSETS
    d.add("HU")
    assert set(_walk(d.root)) == words | {"HUSETS", "HU"}
    d.discard("HUSET")       # BUSET ska finnas kvar
    d.discard("MUS")
    assert set(_walk(d.root)) == (words | {"HUSETS", "HU"}) - {"HUSET", "MUS"}
    assert set(d.words) == set(_walk(d.root))
    # Den gamla strukturen är orörd (en pågående draggenerering påverkas inte).
    assert set(_walk(old_root)) == words


def test_refresh_word_follows_correction_files(tmp_path, rules):
    a = rules.alphabet
    (tmp_path / "words.txt").write_text("hus\nbil\n", encoding="utf-8")
    (tmp_path / "words_strict.txt").write_text("hus\n", encoding="utf-8")
    normal = Dictionary.load(a, tmp_path)
    strict = Dictionary.load(a, tmp_path, mode="strikt")
    add_word("ost", a, tmp_path)
    remove_word("hus", a, tmp_path)
    for w in ("ost", "hus"):
        normal.refresh_word(w)
        strict.refresh_word(w)
    assert set(normal.words) == {"BIL", "OST"}
    assert set(strict.words) == set()
    # Samma resultat som en full omladdning.
    assert normal.words == Dictionary.load(a, tmp_path).words
    assert strict.words == Dictionary.load(a, tmp_path, mode="strikt").words
    add_word("hus", a, tmp_path)   # ångrar borttagningen
    normal.refresh_word("hus"); strict.refresh_word("hus")
    assert "HUS" in normal and "HUS" in strict
