# Wordfeud-motor – specifikation

Hobbyprojekt: ett program som föreslår bästa draget i Wordfeud (svenska) utifrån brädet och min hand. Det simulerar motståndarens möjliga hand och de närmaste dragen med Monte Carlo och rankar dragen efter **vinstchans**.

> Till Claude Code: Läs hela dokumentet först. Bygg i de faser som står under "Byggordning". Stanna efter varje fas, sammanfatta vad som är gjort och hur jag testar det, och vänta på mitt OK innan du går vidare. Ställ frågor om något är oklart i stället för att gissa när det gäller spelregler.

---

## 1. Översikt

- Körs lokalt på datorn som en webbserver. Gränssnittet öppnas i webbläsaren, också från mobilen på samma wifi.
- **Python** används för server, API, lagring, vinstmodell och "lim".
- **C++** används för det prestandakritiska: bräde, draggenerering, poängräkning, simulering och slutspelssökning. Det exponeras till Python via **pybind11**.
- Först skrivs en **referensimplementation i ren Python** av regler och draggenerering. Den används för att kontrollera att C++-versionen ger exakt samma resultat.

## 2. Spelregler som ska stödjas

- Brädet är 15×15. Bonusrutorna är DL (dubbel bokstav), TL (trippel bokstav), DW (dubbelt ord) och TW (trippelt ord). Startrutan är mittrutan.
- **Slumpat bräde:** bonusrutornas placering skiljer sig mellan matcher, så layouten matas in per match. Standardlayouten ska också finnas som snabbval.
- Varje spelare har 7 brickor på hand. Det finns blanka brickor som är värda 0 poäng.
- Bonusrutor räknas bara för brickor som läggs i det aktuella draget. Alla korsord som bildas räknas.
- **Allt i konfig (`config/rules_sv.json`), inget hårdkodat**, men med följande värden. De är hämtade från wordfeud.com/wf/help och wordfeud.co/regler, och de två källorna stämmer överens.

**Svensk brickuppsättning: 104 brickor (102 bokstäver + 2 blanka). Inga Q- eller W-brickor** (men Q och W kan läggas med blank om ordet finns i listan).

| Bokstav | Poäng | Antal | | Bokstav | Poäng | Antal |
|---|---|---|---|---|---|---|
| A | 1 | 9 | | O | 2 | 6 |
| B | 3 | 2 | | P | 4 | 2 |
| C | 8 | 1 | | R | 1 | 8 |
| D | 1 | 5 | | S | 1 | 8 |
| E | 1 | 8 | | T | 1 | 9 |
| F | 3 | 2 | | U | 4 | 3 |
| G | 2 | 3 | | V | 3 | 2 |
| H | 3 | 2 | | X | 8 | 1 |
| I | 1 | 5 | | Y | 7 | 1 |
| J | 7 | 1 | | Z | 8 | 1 |
| K | 3 | 3 | | Å | 4 | 2 |
| L | 2 | 5 | | Ä | 4 | 2 |
| M | 3 | 3 | | Ö | 4 | 2 |
| N | 1 | 6 | | Blank | 0 | 2 |

**Regler:**
- Bokstavsbonus (DL/TL) räknas före ordbonus (DW/TW). Blank är alltid 0 poäng, också på bonusruta. Kontrollexempel från regelsidan: ZON med Z på TL och ordet över en DW ger 54 poäng.
- Lägger man alla 7 brickor i ett drag får man **+40** poäng.
- Första ordet måste täcka mittrutan. Senare drag måste ansluta till befintliga brickor, och alla ord som bildas i båda riktningarna måste vara giltiga.
- **Byte** av en eller flera brickor får bara göras när det finns **minst 7 brickor kvar i påsen**. Pass är alltid tillåtet.
- **Slut på matchen:** när en spelare har använt alla sina brickor och påsen är tom, eller efter upprepade pass. Varje spelares kvarvarande brickpoäng dras från hens egen poäng. Har en spelare gått ut får hen dessutom motståndarens kvarvarande brickpoäng.
- **Pass:** matchen slutar efter **tre pass i rad totalt**, oavsett vilken spelare som passar. Exempel: A passar, B passar, A passar, och matchen är slut. Ett lagt ord nollställer räkningen. **Ett byte räknas inte som pass** och nollställer också räkningen. Antalet pass ligger i konfigen (`consecutive_passes_to_end: 3`). Spara antalet pass i rad i matchens tillstånd, eftersom det påverkar slutspelet.
- Alfabetet är A–Z plus Å, Ä och Ö.
- **Två ordlistelägen:** Wordfeud har en *strikt* svensk ordlista som bara godkänner grundformer, utan böjningar. Stöd båda lägena per match: `normal` med böjningsformer och `strikt` med bara grundformer.

## 3. Ordlista

- Wordfeud använder SAOL (15:e uppl.), men den finns inte öppet. Därför används en öppen lista som approximation, t.ex. SALDO:s fullformslista från Språkbanken, eller DSSO. Hjälp mig hitta och ladda ner en lämplig lista med böjningsformer. Kontrollera licensen.
- Laddaren tar en textfil med ett ord per rad. Den normaliserar till versaler och filtrerar bort ord med tecken utanför alfabetet, bindestreck, mellanslag och siffror. Ordlängd 2–15.
- För strikt läge behövs en lista med bara grundformer (lemman). Med SALDO kan den tas fram ur samma källa.
- **Egna rättelser:** `dict/added.txt` och `dict/removed.txt` läggs ovanpå grundlistan. I gränssnittet finns knappar för "lägg till ord" och "ta bort ord", för när appen godkänner eller nekar något som programmet bedömt annorlunda.
- Ordlistan kompileras till en GADDAG (eller DAWG plus GADDAG) som sparas i binärformat, så att uppstarten blir snabb. Den byggs om automatiskt när källfilerna ändras.

## 4. Speltillstånd och lagring

- Varje match sparas som en JSON-fil i `games/` med:
  - matchnamn/motståndare och datum,
  - bonuslayout (15×15),
  - ordlisteläge (`normal`/`strikt`),
  - lagda brickor: bokstav, position och om brickan är blank (blank lagrad med vald bokstav plus flagga),
  - min nuvarande hand (blank = `?`),
  - min och motståndarens poäng,
  - draglogg (valfri men trevlig: vem, vilket drag, poäng).
- Autospara vid varje ändring. Startsidan listar sparade matcher så att jag kan fortsätta där jag var.
- **Osedda brickor** = full fördelning − brickor på brädet − min hand. Ingen historik behövs för detta. Om de inmatade brickorna överskrider fördelningen visas ett tydligt fel, eftersom det betyder att något är felinmatat.
- Antal brickor i påsen = osedda − 7 (motståndarens hand), med hänsyn till fallet när påsen nästan är slut.

## 5. Gränssnitt (svenska)

Enkelt och funktionellt. Vanilla JS eller något lätt (t.ex. htmx), inget tungt ramverk om det inte behövs. Det ska fungera på mobilskärm.

1. **Ny match:** skapa brädet genom att klicka på rutor och välja bonustyp (DL/TL/DW/TW/ingen), eller välj standardlayout. Ange matchnamn.
2. **Lägg ord på brädet:** välj startruta och riktning (vågrätt/lodrätt) och skriv ordet. Små bokstäver = blank (t.ex. `HUSet`). Programmet visar poängen draget gav och varnar om ordet saknas i ordlistan eller inte ansluter, men låter mig lägga det ändå. Det behövs också en ångra-knapp.
3. **Min hand:** ett textfält med 0–7 tecken, `?` = blank.
4. **Poäng:** fält för båda spelarnas poäng, som uppdateras automatiskt när drag läggs men går att korrigera manuellt.
5. **Analys:** knappen "Analysera" visar en tabell med kandidatdrag: ord, position, poäng, kvarvarande brickor, vinstchans (%), förväntad marginal och antal simuleringar. Tabellen uppdateras löpande medan simuleringen pågår. Man ska kunna klicka på ett drag för att förhandsvisa det på brädet och lägga det med en knapp.
6. **Inställningar** (sparas):
   - motståndarmodell: **Perfekt** eller **Mänsklig** (se 6.3),
   - **antal drag framåt** (plies) att simulera, t.ex. 1–6,
   - antal kandidatdrag att simulera (standard 15–20),
   - stoppvillkor: antal iterationer eller tidsbudget i sekunder,
   - sortering: **vinstchans** (standard, marginal som tiebreak) eller **förväntad marginal**,
   - om byten och pass ska tas med som kandidater (standard: ja).

## 6. Motorn

### 6.1 Draggenerering
- GADDAG-baserad generering av alla lagliga drag med ankarrutor och förberäknade korskontroller (cross-checks) per ruta, i båda riktningarna.
- Hanterar blanka brickor, första draget över mittrutan, byten (alla unika delmängder av handen) och pass.
- Poängräkningen är inbyggd i genereringen.

### 6.2 Statisk värdering
- Värde = poäng + **leave-värde** (värdet av de brickor som blir kvar på hand).
- Version 1 är ett heuristiskt leave-värde (t.ex. bonus för blank och S, straff för dubbletter, obalans mellan vokaler och konsonanter, och svåra bokstäver).
- Version 2 (senare): leave-värden tränade via självspel. Fältet ska kunna bytas ut via fil.

### 6.3 Motståndarmodeller
- **Perfekt:** väljer draget med högst statisk värdering.
- **Mänsklig:** softmax-urval över de bästa dragen med justerbar "temperatur" och top-N. Eventuellt ett läge där motståndaren bara känner till vanliga ord (kräver ordfrekvenslista, gör det senare och valfritt).

### 6.4 Monte Carlo-simulering
1. Generera alla mina drag och ta de K bästa efter statisk värdering (plus byten och pass).
2. För varje iteration: slumpa motståndarens hand och påsens ordning bland de osedda brickorna, med hänsyn till exakt antal per bokstav. Använd **samma slumpdragning för alla kandidater** i en iteration, så att jämförelsen blir rättvisare (common random numbers).
3. Spela kandidatdraget och sedan N plies framåt. Båda sidor väljer drag med vald policy: motståndaren enligt sin modell, jag själv med statisk värdering. Dra nya brickor ur påsen.
4. I slutet av rollouten görs ställningen om till vinstchans med vinstmodellen (6.5). Eventuellt kvarvarande leave-värden räknas in.
5. Spara medelvärde och standardfel per kandidat. Visa resultat löpande och stoppa vid iterations- eller tidsgräns.
6. Bonus: rensa bort kandidater som är statistiskt klart sämre (enkel successive rejection) och lägg tiden på de jämna.
- Flertrådat i C++ (en tråd per kärna) med en separat RNG per tråd. Sätt en fast seed så att resultat går att reproducera vid felsökning.

### 6.5 Vinstmodell
- Indata: poängskillnad, antal osedda brickor (hur långt kvar spelet är) och vem som är på tur.
- Version 1: en enkel analytisk modell, P(vinst) = Φ(marginal / σ(brickor kvar)), där σ krymper mot slutet.
- Version 2: logistisk regression eller ett litet nätverk tränat på självspelade matcher. Själva träningen gör jag gärna själv, så bygg infrastrukturen: självspelsskript som loggar ställningar och utfall till fil.

### 6.6 Slutspel
- När påsen är tom är informationen fullständig. Kör då exakt sökning med alfa-beta/minimax och transpositionstabell, med vinst (och sedan marginal) som mål.
- Pre-endgame (1–7 brickor i påsen) kan i första versionen hanteras av den vanliga simuleringen. Exakt uppräkning av påsen är en möjlig senare förbättring.

## 7. Projektstruktur (förslag)

```
wordfeud-motor/
  CLAUDE.md            # kort sammanfattning + hur man bygger/testar
  SPEC.md              # detta dokument
  config/rules_sv.json
  dict/                # källistor + added.txt / removed.txt (+ kompilerad binär, gitignored)
  games/               # sparade matcher (gitignored)
  core/                # C++: board, gaddag, movegen, sim, endgame + pybind11-bindings
  wfengine/            # Python-paket: referensimpl, modeller, lagring, självspel
  server/              # FastAPI-app + statiska webbfiler
  tests/
```
- Bygg med CMake plus scikit-build-core (eller motsvarande) så att `pip install -e .` kompilerar C++-delen.
- Ett kommando för att starta: t.ex. `python -m server`, som skriver ut vilken adress mobilen ska använda på det lokala nätet.

## 8. Tester
- Poängräkning: korsord, blanka, bonus bara på nya brickor, bonus för alla 7 brickor, första draget.
- Draggenerering: Python-referensen och C++ ska ge **identiska dragmängder och poäng** på ett stort antal slumpade ställningar.
- Osedda brickor: korrekt räkning och felmeddelande vid överskridande.
- Slutspel: små handkonstruerade ställningar med känt svar.
- Prestandamätning: drag per sekund och simuleringsiterationer per sekund.

## 9. Byggordning (stanna efter varje fas)
1. **Grund:** konfig, ordlisteladdare med rättelsefiler, bräde, poängräkning och draggenerering i ren Python, med tester.
2. **Lagring + gränssnitt (manuellt):** skapa bräde, lägg ord, hand, poäng, spara/ladda matcher. Analysen visar bara statiskt rankade drag.
3. **C++-kärna:** GADDAG, draggenerering och poängräkning, korstestade mot Python-versionen.
4. **Monte Carlo-simulering** med båda motståndarmodellerna, val av antal plies, löpande resultat i gränssnittet och vinstmodell v1.
5. **Slutspelssökning.**
6. **Senare/valfritt:** självspel för leave-värden och vinstmodell v2, ordfrekvenser för den mänskliga motståndaren, inläsning av skärmdumpar.
