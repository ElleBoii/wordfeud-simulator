# Wordfeud-motor

Se SPEC.md för fullständig specifikation och byggordning (stanna efter varje fas).

## Status
- Fas 1 (klar): `wfengine/` – regler (config/rules_sv.json, verifierade utom standardlayout), ordlista + DAWG (lägen normal/strikt), bräde, poäng, draggenerering, osedda brickor, matchslutsregler i ren Python.

- Fas 2 (klar): `wfengine/game.py` (matchtillstånd, ångra, lagring i games/), `server/` (FastAPI + vanilla JS i server/static). Analys = statisk rankning efter poäng.

## Kommandon
- Starta: `python -m server` (port 8000, skriver ut LAN-adress för mobilen)
- Beroenden: `python -m pip install fastapi uvicorn httpx pytest`
- Tester: `python -m pytest -q`  (brute force-korstest av draggenerering ingår, ~20 s)
- Hämta ordlista: `python scripts/fetch_saldo.py` → dict/words.txt + dict/words_strict.txt (SALDOM, CC BY 4.0)
- Demo/prestanda: `python scripts/demo.py ARSTL?E [normal|strikt]`

## Konventioner
- Koordinater (rad, kolumn), 0-indexerade, startruta (7,7).
- Blank: `?` i handen; på brädet versal bokstav + `blank=True`; i ordtext gemen.
- Bonuskoder i layout: `.` `d`=DL `t`=TL `D`=DW `T`=TW.
- Inga regelvärden hårdkodade – allt i config/rules_sv.json (flaggor `verified`).
- Python-referensen använder Appel–Jacobson/DAWG; C++ (fas 3) ska använda GADDAG och ge identiska dragmängder (`Move.key`) och poäng.
- Rättelser: normal = added/removed.txt; strikt = added_strict/removed_strict.txt + removed.txt. Se wfengine/dictionary.py.
- Passräkning: tre pass i rad totalt avslutar; byte nollställer (wfengine/rules.py). Antal pass i rad ska sparas i matchtillståndet (fas 2).
