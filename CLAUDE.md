# Wordfeud-motor

Se SPEC.md för fullständig specifikation och byggordning (stanna efter varje fas).

## Status
- Fas 1 (klar): `wfengine/` – regler (config/rules_sv.json, verifierade utom standardlayout), ordlista + DAWG (lägen normal/strikt), bräde, poäng, draggenerering, osedda brickor, matchslutsregler i ren Python.

- Fas 2 (klar): `wfengine/game.py` (matchtillstånd, ångra, lagring i games/), `server/` (FastAPI + vanilla JS i server/static). Analys = statisk rankning efter poäng.
- Fas 3 (C++) är uppskjuten. Ingen C++-kompilator är installerad (kräver Visual Studio Build Tools + pybind11).
- Fas 4 (klar, ren Python): Monte Carlo-simulering.
  - `wfengine/fastgen.py`: draggenerering med inbyggd poäng, ~3× snabbare, korstestad mot movegen.
  - `wfengine/evaluation.py`: leave-värde och vinstmodell v1, parametrar i `config/sim_sv.json`.
  - `wfengine/sim.py`: policyer, rollout och gallring.
  - `wfengine/simrunner.py`: körning inline eller i processpool.
  - `server/simjobs.py`: jobb och inställningar, sparas i `settings.json` (gitignored).
  - API: `POST /api/games/{id}/simulate`, `GET /api/sim/{job}`, `POST /api/sim/{job}/stop`, `GET/PUT /api/settings`.

## Kommandon
- Starta: `python -m server` (port 8000, skriver ut LAN-adress för mobilen)
- Beroenden: `python -m pip install fastapi uvicorn httpx pytest`
- Tester: `python -m pytest -q`  (brute force-korstest av draggenerering ingår, ~20 s)
- Hämta ordlista: `python scripts/fetch_saldo.py` → dict/words.txt + dict/words_strict.txt (SALDOM, CC BY 4.0)
- Demo/prestanda: `python scripts/demo.py ARSTL?E [normal|strikt]`

## Konventioner
- Koordinater (rad, kolumn), 0-indexerade, startruta (7,7).
- Blank: `?` i handen; på brädet versal bokstav + `blank=True`; i ordtext gemen.
- Bonusantal:
  - Ett nytt matchbräde måste ha exakt `board.bonus_counts` i config: 24 DL, 20 TL, 12 DW, 8 TW.
  - Kontrolleras med `check_bonus_counts` i `Game.new`.
  - Gamla sparade matcher kontrolleras inte.
  - Slumpat bräde (i JS) lägger aldrig bonus på startrutan.
- Bonuskoder i layout: `.` `d`=DL `t`=TL `D`=DW `T`=TW.
- Inga regelvärden hårdkodade – allt i config/rules_sv.json (flaggor `verified`).
- Python-referensen använder Appel–Jacobson/DAWG; C++ (fas 3) ska använda GADDAG och ge identiska dragmängder (`Move.key`) och poäng.
- Rättelser: normal = added/removed.txt; strikt = added_strict/removed_strict.txt + removed.txt. Se wfengine/dictionary.py.
- Simuleringsbudget (`wfengine/budget.py`, `config/sim_sv.json` → `budget`):
  - Drag framåt kan vara 1–5, 10 eller 0 (= till slutet, med taket `END_PLIES` = 100).
  - Iterationer är enda stoppvillkoret.
  - Före start kalibreras tiden per drag i ställningen. Mitt drag mäts med kandidaternas leave när blanka sparas.
  - Max iterationer sätts så att körningen ryms inom `max_seconds` × `safety`.
  - Ryms inte ens en iteration nekas starten (`BudgetError`).
  - `max_seconds` är också en hård gräns under körningen.
  - Känt: uppskattningen kan slå fel med 0,9–1,7× på grund av brus i kalibreringen. Idé: adaptivt mål från uppmätt hastighet.
- Simulering:
  - En rollout är en ren funktion av (kontext, kandidat, iteration).
  - Slumpdragningen beror bara på (seed, iteration), alltså samma för alla kandidater (common random numbers).
  - Processpoolen ger därför identiska resultat med inline-körning (testat).
  - Arbetsprocesserna laddar ordlistan själva (~3,5 s, ~170 MB per process).
- Passräkning: tre pass i rad totalt avslutar; byte nollställer (wfengine/rules.py). Antal pass i rad ska sparas i matchtillståndet (fas 2).
