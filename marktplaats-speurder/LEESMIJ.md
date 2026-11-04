# Marktplaats Speurder

Chrome-extensie die meerdere zoekopdrachten op Marktplaats in de gaten houdt en meldt zodra er een **nieuwe** advertentie online komt.

## Installeren
1. Pak de zip uit naar een vaste map.
2. Ga naar `chrome://extensions` en zet **Ontwikkelaarsmodus** aan (rechtsboven).
3. Klik **Uitgepakte extensie laden** en kies de map `marktplaats-speurder`.
4. De instellingenpagina opent vanzelf. Pin de extensie via het puzzelstukje, dan zie je het teller-badge.

## Zoekopdrachten
Klik **+ Nieuwe zoekopdracht**. Per zoekopdracht kun je instellen:
- **Zoekterm** en/of **categorie + subcategorie**.
- **Prijs** van/tot (in euro's).
- **Postcode + afstand**.
- **Conditie** (nieuw, zo goed als nieuw, gebruikt, …). De opties komen uit de gekozen categorie zelf, want die verschillen per categorie (bij auto's is "Gebruikt" een andere waarde dan bij fietsen).
- **Uitsluiten**: woorden in de titel die je niet wilt zien (bijv. `gezocht, defect, onderdelen`).
- **Betaalde promoties altijd overslaan**: standaard uit. Een dagtopper wordt alleen gemeld als de advertentie zelf echt nieuw is; zet dit aan als je ook nieuwe advertenties met een dagtopper niet wilt zien.
- **Laat Claude beoordelen**: beschrijf in je eigen woorden wat je zoekt (zie hieronder).
- **Actief**: tijdelijk pauzeren zonder te verwijderen.

Met **Testen** zie je meteen wat de zoekopdracht nu oplevert: hoeveel betaalde promoties en winkeladvertenties er bovenaan staan, en de nieuwste gewone advertenties met hun datum.

Een zoekopdracht met alleen een categorie (zonder zoekterm) werkt ook.

## Claude laten beoordelen
Krijg je te veel resultaten, beschrijf dan bij een zoekopdracht in gewone taal wat je zoekt, bijvoorbeeld:

> Een Bambu Lab A1 of A1 mini, liefst met AMS lite, werkend en in goede staat. Geen losse onderdelen of filament, geen gezocht-advertenties.

Claude bekijkt dan elke nieuwe advertentie (titel, prijs, omschrijving, plaats) en laat alleen door wat erbij past. In de pop-up staat bij elke advertentie in één zin waarom hij past, en onder **Afgekeurd door Claude** zie je wat er is tegengehouden en waarom. Zo kun je je omschrijving bijstellen. Met **Testen** in de editor zie je meteen hoe Claude de tien nieuwste advertenties beoordeelt.

Tips:
- Noem wat je **niet** wilt ("geen onderdelen", "geen ruilen", "geen bieden"), dat werkt het best.
- Zegt een advertentie iets niet (bijv. de staat), dan laat Claude hem standaard door. Wil je dat niet, schrijf dan "alleen als de staat vermeld is" of "wees streng".
- De zoekterm en filters blijven het eerste zeef; Claude beoordeelt alleen wat daarna overblijft.

### Via je Claude-abonnement (standaard, geen extra kosten)
De beoordeling loopt via de pagina **[Marktplaats Triage](https://claude.ai/artifact/PFrhocoSYukf1XQ4atgc6S)** op claude.ai. Die pagina vraagt Claude om een oordeel met je eigen Claude-account, net als een chatbericht; het telt mee voor het gebruik van je abonnement, maar kost niets extra.

1. Open de triage-pagina in Chrome (dezelfde browser als de extensie) en zet het tabblad vast (rechtsklik op het tabblad → *Vastzetten*).
2. Klik eenmalig op **Starten** en geef Claude toestemming.
3. Laat het tabblad openstaan. Bovenaan staat of de extensie verbonden is; daaronder zie je per zoekopdracht wat Claude heeft doorgelaten en afgekeurd.

Is de pagina dicht, of staat hij op **Pauzeren**, dan wachten nieuwe advertenties en worden ze beoordeeld zodra de pagina weer klaarstaat (je ziet dan een oranje **!** en in de pop-up een link naar de pagina). Na het bijwerken van de extensie: herlaad het triage-tabblad één keer.

### Via een API-sleutel (betaald, zonder open tabblad)
Kies onder Instellingen → Claude voor *Via een API-sleutel* als je de pagina niet open wilt houden. Maak een sleutel aan op [platform.claude.com](https://platform.claude.com/) (daar heb je tegoed nodig), plak hem in **API-sleutel** en controleer hem met **Testen**. Kies een **model**: standaard Claude Opus 5.5 (ongeveer $0,20 per 100 beoordeelde advertenties), Claude Sonnet 5.5 kost ongeveer de helft, Claude Haiku 5.5 ongeveer $0,01 per 100. De sleutel blijft alleen in deze browser en gaat niet mee in de back-up.

Bij beide manieren gaan de advertentiegegevens (titel, prijs, omschrijving, plaats) en je omschrijving naar Claude (Anthropic). Lukt een beoordeling even niet, dan wachten de nieuwe advertenties en worden ze de volgende ronde alsnog beoordeeld. Haal je de omschrijving weg, dan komen wachtende advertenties gewoon door.

## Wat telt als nieuw?
Alleen advertenties die **na de vorige controle geplaatst** zijn. Bij het opslaan onthoudt de Speurder wat er nu al staat; daarna meldt hij alleen nieuw geplaatste advertenties. Pas je de filters aan, dan begint hij opnieuw.

Marktplaats zet bij "nieuwste eerst" ook oude advertenties bovenaan: dagtoppers, betaald omhoog geplaatste advertenties en winkeladvertenties (Admarkt). Die krijgen allemaal de datum *Vandaag*. De Speurder herkent ze zo:
- Elke gewone advertentie heeft een volgnummer (`m2455384599`) dat oploopt met het moment van plaatsen en gelijk blijft als de advertentie omhoog wordt geplaatst. Alleen advertenties met een nummer hoger dan wat al bekend was, tellen als nieuw (met een marge van een paar uur voor advertenties die iets later online komen). Wat al online stond toen je de zoekopdracht opsloeg, telt nooit als nieuw.
- Per controleronde haalt de Speurder één keer het nieuwste volgnummer van heel Marktplaats op (uit de drukke categorie Huis en Inrichting). Zo heeft ook een smalle zoekopdracht, waarvan de nieuwste advertentie dagen oud is, een actueel ijkpunt.
- Advertenties met een datum van vóór de vorige controle tellen nooit als nieuw.
- Winkeladvertenties en "vergelijkbare advertenties" die Marktplaats aanvult en niet bij je zoekterm passen, tellen nooit mee.
- Bij brede zoekopdrachten kijkt de Speurder verder dan de eerste pagina, voorbij de dagtoppers, tot hij een pagina zonder nieuwe advertenties tegenkomt (maximaal 500 resultaten per controle).

Op de instellingenpagina zie je per zoekopdracht wat de laatste controle heeft overgeslagen, en een waarschuwing als een zoekopdracht op Marktplaats helemaal niets vindt.

## Meldingen
- **Pop-up** (klik op het icoon): lijst met nieuwe advertenties, met foto, prijs, plaats en afstand. Ongelezen zijn gemarkeerd; het badge-getal telt ze. Met ⟳ controleer je direct.
- **Bureaubladmelding** per nieuwe advertentie; klik erop om de advertentie te openen. Komen er in één keer meer binnen dan ingesteld (standaard 3), dan krijg je één samenvatting.
- Een oranje **!** op het icoon betekent dat Marktplaats bij de laatste controle een fout gaf. De foutmelding staat in de pop-up.

## Algemeen
- Standaard wordt elke **5 minuten** gecontroleerd (instelbaar van 1 minuut tot 1 uur). Zoekopdrachten worden na elkaar opgehaald, met een korte pauze ertussen.
- Werkt alleen terwijl Chrome open is.
- **Exporteren/Importeren** bewaart je zoekopdrachten en instellingen als JSON-bestand.

## Hoe het werkt (API)
Marktplaats heeft **geen openbare API** voor zoeken. De website haalt zijn zoekresultaten zelf op bij `https://www.marktplaats.nl/lrp/api/search` (JSON, geen sleutel nodig). Deze extensie gebruikt hetzelfde adres, gesorteerd op *nieuwste eerst* en met het filter *aangeboden sinds*. Dezelfde aanpak gebruikt de open-source Python-bibliotheek [marktplaats-py](https://github.com/jensjeflensje/marktplaats-py), waar ook de categorielijst (`categories.js`) vandaan komt.

Omdat dit adres niet officieel is, kan Marktplaats het zonder aankondiging wijzigen. Gaat er iets mis, dan zie je de fout in de pop-up en op de instellingenpagina.

Voor Claude gebruikt de extensie de officiële Anthropic-SDK (`@anthropic-ai/sdk`), als één gebundeld bestand in `vendor/anthropic-sdk.mjs`, omdat een extensie zonder bouwstap geen npm-pakketten kan laden. Bijwerken naar een nieuwere SDK-versie:

```bash
npm install @anthropic-ai/sdk@<versie> esbuild
echo "export { default } from '@anthropic-ai/sdk';" > entry.mjs
npx esbuild entry.mjs --bundle --format=esm --platform=browser --target=chrome120 --minify --legal-comments=inline --outfile=vendor/anthropic-sdk.mjs
```

Pas daarna het versienummer in de eerste regel van dat bestand aan.
