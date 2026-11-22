"""Ordlisteladdare och minimerad DAWG (referensimplementation i ren Python).

Två lägen (per match):
  normal: words.txt (med böjningsformer)
          ordmängd = (words ∪ added) − removed
  strikt: words_strict.txt (bara grundformer)
          ordmängd = (words_strict ∪ added_strict) − removed − removed_strict

Ett ord som nekas i normalt läge är alltså borta i båda lägena, och ett ord
som godkänns i strikt läge (en grundform) godkänns i båda.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

MIN_LEN = 2
MAX_LEN = 15

DEFAULT_DICT_DIR = Path(__file__).resolve().parent.parent / "dict"
NORMAL, STRICT = "normal", "strikt"
MODES = (NORMAL, STRICT)
BASE_FILES = {NORMAL: "words.txt", STRICT: "words_strict.txt"}
ADDED_FILE = "added.txt"
REMOVED_FILE = "removed.txt"
ADDED_STRICT_FILE = "added_strict.txt"
REMOVED_STRICT_FILE = "removed_strict.txt"


def normalize(word: str, alphabet: str, max_len: int = MAX_LEN) -> str | None:
    """Versaler, och None om ordet har otillåtna tecken eller fel längd."""
    w = word.strip().upper()
    if not (MIN_LEN <= len(w) <= max_len):
        return None
    allowed = set(alphabet)
    if any(ch not in allowed for ch in w):
        return None
    return w


def read_word_file(path: str | Path) -> Iterator[str]:
    """Läser en ordfil rad för rad (UTF-8, med latin-1 som reserv).
    Rader som börjar med # ignoreras."""
    path = Path(path)
    if not path.exists():
        return
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def clean_words(words: Iterable[str], alphabet: str, max_len: int = MAX_LEN) -> set[str]:
    out = set()
    for w in words:
        n = normalize(w, alphabet, max_len)
        if n:
            out.add(n)
    return out


class Node:
    __slots__ = ("children", "final")

    def __init__(self) -> None:
        self.children: dict[str, Node] = {}
        self.final = False


def build_dawg(words: Iterable[str]) -> Node:
    """Bygger en minimerad DAWG (Daciuks inkrementella algoritm, sorterad indata)."""
    root = Node()
    register: dict[tuple, Node] = {}
    unchecked: list[tuple[Node, str, Node]] = []

    def key(n: Node) -> tuple:
        return (n.final, tuple((ch, id(c)) for ch, c in sorted(n.children.items())))

    def minimize(down_to: int) -> None:
        while len(unchecked) > down_to:
            parent, ch, child = unchecked.pop()
            k = key(child)
            existing = register.get(k)
            if existing is not None:
                parent.children[ch] = existing
            else:
                register[k] = child

    prev = ""
    for word in sorted(set(words)):
        cp = 0
        while cp < len(prev) and cp < len(word) and prev[cp] == word[cp]:
            cp += 1
        minimize(cp)
        node = unchecked[-1][2] if unchecked else root
        for ch in word[cp:]:
            nxt = Node()
            node.children[ch] = nxt
            unchecked.append((node, ch, nxt))
            node = nxt
        node.final = True
        prev = word
    minimize(0)
    return root


def _clone(n: Node) -> Node:
    c = Node()
    c.children = dict(n.children)
    c.final = n.final
    return c


def _corrections(dict_dir: Path, mode: str, alphabet: str, max_len: int) -> tuple[set[str], set[str]]:
    """(tillagda, borttagna) för ett läge enligt rättelsefilerna."""
    def read(name):
        return clean_words(read_word_file(dict_dir / name), alphabet, max_len)
    if mode == NORMAL:
        return read(ADDED_FILE), read(REMOVED_FILE)
    return read(ADDED_STRICT_FILE), read(REMOVED_FILE) | read(REMOVED_STRICT_FILE)


class Dictionary:
    def __init__(self, words: Iterable[str]) -> None:
        self.mode = NORMAL
        self.words: set[str] = set(words)
        self.base_words: frozenset[str] = frozenset(self.words)
        self.root = build_dawg(self.words)
        self._source: tuple | None = None   # (dict_dir, alphabet, max_len) vid load()

    def __contains__(self, word: str) -> bool:
        return word in self.words

    def __len__(self) -> int:
        return len(self.words)

    def node_for_prefix(self, prefix: str) -> Node | None:
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    # --- snabba ändringar utan ombyggnad -----------------------------------
    # DAWG:en delar noder mellan ord, så hela vägen från roten klonas innan den
    # ändras. Den gamla strukturen lämnas orörd, vilket gör att en pågående
    # draggenerering kan läsa vidare i den utan att störas.
    def add(self, word: str) -> None:
        if word in self.words:
            return
        root = _clone(self.root)
        node = root
        for ch in word:
            child = node.children.get(ch)
            child = _clone(child) if child is not None else Node()
            node.children[ch] = child
            node = child
        node.final = True
        self.words.add(word)
        self.root = root

    def discard(self, word: str) -> None:
        if word not in self.words:
            return
        root = _clone(self.root)
        node = root
        for ch in word:
            child = _clone(node.children[ch])
            node.children[ch] = child
            node = child
        node.final = False
        self.words.discard(word)
        self.root = root

    def refresh_word(self, word: str) -> None:
        """Räknar om om ett ord ska vara med, utifrån grundlistan och rättelsefilerna."""
        if self._source is None:
            return
        dict_dir, alphabet, max_len = self._source
        w = normalize(word, alphabet, max_len)
        if w is None:
            return
        added, removed = _corrections(dict_dir, self.mode, alphabet, max_len)
        if (w in self.base_words or w in added) and w not in removed:
            self.add(w)
        else:
            self.discard(w)

    @classmethod
    def from_words(cls, words: Iterable[str], alphabet: str, max_len: int = MAX_LEN) -> "Dictionary":
        return cls(clean_words(words, alphabet, max_len))

    @classmethod
    def load(cls, alphabet: str, dict_dir: str | Path = DEFAULT_DICT_DIR,
             mode: str = NORMAL, max_len: int = MAX_LEN) -> "Dictionary":
        if mode not in MODES:
            raise ValueError(f"Okänt ordlisteläge {mode!r}, välj {MODES}")
        dict_dir = Path(dict_dir)
        base = clean_words(read_word_file(dict_dir / BASE_FILES[mode]), alphabet, max_len)
        added, removed = _corrections(dict_dir, mode, alphabet, max_len)
        d = cls((base | added) - removed)
        d.base_words = frozenset(base)
        d.mode = mode
        d._source = (dict_dir, alphabet, max_len)
        return d


# --- Rättelsefiler -----------------------------------------------------------

def _rewrite(path: Path, words: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(w + "\n" for w in sorted(words)), encoding="utf-8")


def add_word(word: str, alphabet: str, dict_dir: str | Path = DEFAULT_DICT_DIR,
             mode: str = NORMAL) -> str:
    """Godkänn ett ord. Normalt läge: added.txt. Strikt läge: added_strict.txt
    och dessutom added.txt (en giltig grundform är giltig även i normalt läge)."""
    dict_dir = Path(dict_dir)
    if mode == STRICT:
        _correct(word, alphabet, dict_dir, ADDED_STRICT_FILE, REMOVED_STRICT_FILE)
    return _correct(word, alphabet, dict_dir, ADDED_FILE, REMOVED_FILE)


def remove_word(word: str, alphabet: str, dict_dir: str | Path = DEFAULT_DICT_DIR,
                mode: str = NORMAL) -> str:
    """Neka ett ord. Normalt läge: removed.txt (gäller båda lägena).
    Strikt läge: bara removed_strict.txt (ordet kan vara en giltig böjningsform)."""
    dict_dir = Path(dict_dir)
    if mode == STRICT:
        return _correct(word, alphabet, dict_dir, REMOVED_STRICT_FILE, ADDED_STRICT_FILE)
    return _correct(word, alphabet, dict_dir, REMOVED_FILE, ADDED_FILE)


def _correct(word: str, alphabet: str, dict_dir: Path, into: str, out_of: str) -> str:
    w = normalize(word, alphabet)
    if w is None:
        raise ValueError(f"Ogiltigt ord: {word!r}")
    target = set(read_word_file(dict_dir / into))
    other = set(read_word_file(dict_dir / out_of))
    target.add(w)
    if w in other:
        other.discard(w)
        _rewrite(dict_dir / out_of, other)
    _rewrite(dict_dir / into, target)
    return w
