"""Laddar ner SALDO:s fullformslexikon (SALDOM) och skriver dict/words.txt.

Källa: Språkbanken Text, Göteborgs universitet – SALDOM
  https://sprakbanken.se/resurser/saldom   (DOI 10.23695/agcm-ny22)
Licens: CC BY 4.0 – kräver attribuering (står överst i words.txt).

SALDO är en approximation av SAOL. Använd dict/added.txt och dict/removed.txt
för att rätta när appen bedömer ett ord annorlunda.

Användning:  python scripts/fetch_saldo.py [--xml sökväg-till-befintlig-saldom.xml]
"""
from __future__ import annotations

import argparse
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wfengine.dictionary import normalize  # noqa: E402
from wfengine.rules import load_rules      # noqa: E402

URL = "https://svn.spraakbanken.gu.se/sb-arkiv/pub/lmf/saldom/saldom.xml"
DICT_DIR = ROOT / "dict"

# Ordklasser som inte är giltiga i Wordfeud: egennamn och förkortningar,
# prefix/suffix-led (sxc, mxc) och ordklasser för flerordsuttryck (slutar på m)
# eller led (slutar på h).
SKIP_POS = {"pm", "pma", "nna", "ava", "aba", "vba", "ppa", "pna", "kna", "sna", "sxc", "mxc"}


def skip_pos(pos: str | None) -> bool:
    return pos is None or pos in SKIP_POS or (len(pos) == 3 and pos[2] in "mh")
# Morfologikoder för sammansättningsled (inte fristående ord).
SKIP_MSD = {"c", "ci", "cm", "sms"}

HEADER = """# Ordlista härledd ur SALDOM (Språkbanken Text, Göteborgs universitet),
# https://sprakbanken.se/resurser/saldom, licens CC BY 4.0
# (https://creativecommons.org/licenses/by/4.0/). Bearbetad: endast böjningsformer,
# egennamn/förkortningar/sammansättningsled borttagna, versaler, 2–15 bokstäver.
"""


def download(dest: Path) -> None:
    print(f"Laddar ner {URL} (~240 MB) ...")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(URL) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done >> 20} / {total >> 20} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def extract(xml_path: Path, alphabet: str) -> tuple[set[str], set[str], Counter]:
    """Ger (alla böjningsformer, grundformer/lemman, statistik)."""
    words: set[str] = set()
    lemmas: set[str] = set()
    skipped = Counter()
    pos = None
    for event, elem in ET.iterparse(xml_path, events=("end",)):
        tag = elem.tag
        if tag == "FormRepresentation":
            feats = {f.get("att"): f.get("val") for f in elem}
            pos = feats.get("partOfSpeech")
            base = feats.get("writtenForm", "")
            if not skip_pos(pos) and base == base.lower():
                w = normalize(base, alphabet)
                if w:
                    lemmas.add(w)
        elif tag == "WordForm":
            feats = {f.get("att"): f.get("val") for f in elem}
            form, msd = feats.get("writtenForm", ""), feats.get("msd", "")
            if skip_pos(pos):
                skipped[f"pos:{pos}"] += 1
            elif msd in SKIP_MSD or ":" in msd:   # "invar 1:2-4" = del av flerordsuttryck
                skipped["sammansättningsled/flerordsdel"] += 1
            elif form != form.lower():
                skipped["versaler (namn)"] += 1
            else:
                w = normalize(form, alphabet)
                if w:
                    words.add(w)
                else:
                    skipped["ogiltiga tecken/längd"] += 1
        elif tag == "LexicalEntry":
            pos = None
            elem.clear()
    return words, lemmas, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", type=Path, help="använd en redan nedladdad saldom.xml")
    args = ap.parse_args()

    rules = load_rules()
    xml_path = args.xml or DICT_DIR / "saldom.xml"
    if not xml_path.exists():
        DICT_DIR.mkdir(exist_ok=True)
        download(xml_path)

    print("Extraherar ordformer ...")
    words, lemmas, skipped = extract(xml_path, rules.alphabet)
    for name, ws, note in [("words.txt", words, "alla böjningsformer"),
                           ("words_strict.txt", lemmas, "bara grundformer (strikt läge)")]:
        out = DICT_DIR / name
        out.write_text(HEADER + f"# Innehåll: {note}.\n" + "".join(w + "\n" for w in sorted(ws)),
                       encoding="utf-8")
        print(f"Skrev {len(ws):,} ord till {out}")
    for k, v in skipped.most_common():
        print(f"  överhoppade {k}: {v:,}")


if __name__ == "__main__":
    main()
