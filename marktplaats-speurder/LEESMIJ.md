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
- **Conditie** (nieuw, zo goed als nieuw, gebruikt, …).
- **Uitsluiten**: woorden in de titel die je niet wilt zien (bijv. `gezocht, defect, onderdelen`).
- **Topadvertenties en dagtoppers overslaan**: dat zijn betaalde plaatsingen, vaak oud.
- **Actief**: tijdelijk pauzeren zonder te verwijderen.

Met **Testen** zie je meteen wat de zoekopdracht nu oplevert, zodat je de filters kunt controleren voordat je opslaat.

Bij het opslaan worden alle advertenties die er nu al staan als *bekend* gemarkeerd. Je krijgt daarna alleen nog advertenties die nieuw verschijnen. Pas je de filters aan, dan gebeurt dat opnieuw (zo krijg je geen stortvloed aan oude advertenties).

## Meldingen
- **Pop-up** (klik op het icoon): lijst met nieuwe advertenties, met foto, prijs, plaats en afstand. Ongelezen zijn gemarkeerd; het badge-getal telt ze. Met ⟳ controleer je direct.
- **Bureaubladmelding** per nieuwe advertentie; klik erop om de advertentie te openen. Komen er in één keer meer binnen dan ingesteld (standaard 3), dan krijg je één samenvatting.
- Een oranje **!** op het icoon betekent dat Marktplaats bij de laatste controle een fout gaf. De foutmelding staat in de pop-up.

## Algemeen
- Standaard wordt elke **5 minuten** gecontroleerd (instelbaar van 1 minuut tot 1 uur). Zoekopdrachten worden na elkaar opgehaald, met een korte pauze ertussen.
- Werkt alleen terwijl Chrome open is.
- **Exporteren/Importeren** bewaart je zoekopdrachten en instellingen als JSON-bestand.

## Hoe het werkt (API)
Marktplaats heeft **geen openbare API** voor zoeken. De website haalt zijn zoekresultaten zelf op bij `https://www.marktplaats.nl/lrp/api/search` (JSON, geen sleutel nodig). Deze extensie gebruikt hetzelfde adres, gesorteerd op *nieuwste eerst*. Dezelfde aanpak gebruikt de open-source Python-bibliotheek [marktplaats-py](https://github.com/jensjeflensje/marktplaats-py), waar ook de categorielijst (`categories.js`) vandaan komt.

Omdat dit adres niet officieel is, kan Marktplaats het zonder aankondiging wijzigen. Gaat er iets mis, dan zie je de fout in de pop-up en op de instellingenpagina.
