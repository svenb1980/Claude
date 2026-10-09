# Planon Verlof Goedkeurder

Chrome-extensie voor **Planon Self-Service → Requests to approve**.

## Installeren
1. Pak de zip uit naar een vaste map.
2. Ga naar `chrome://extensions` en zet **Ontwikkelaarsmodus** aan (rechtsboven).
3. Klik **Uitgepakte extensie laden** en kies de map `planon-leave-approver`.
4. Open (of ververs) de pagina *Requests to approve*. Rechtsonder verschijnt het paneel **Verlof goedkeuren**.

## Automatisch (standaard aan)
Zodra *Requests to approve* opent, start **Controleren + goedkeuren** vanzelf na 2 seconden, zonder klikken. Elke aanvraag wordt één keer per paginabezoek behandeld; een aanvraag die niet door de urencontrole komt blijft in Planon staan en wordt pas na verversen opnieuw bekeken. Uitzetten kan onder *Instellingen urencontrole* → *Automatisch controleren + goedkeuren zodra de lijst opent*.

## Rapport naar Cyberdeck
Na elke run gaat een rapport naar Cyberdeck (via `background.js` en `bridge.js`, die in claude.ai meedraait):
- **Goedgekeurd** → notitie "Leave approved: naam" met periode en uren.
- **Uren kloppen niet** → actie "Leave request naam: hours don't match" met de reden (bijv. *# Hours says 6h, but From/Till gives 4h*).
- Niet bevestigd door Planon, of niet aan toegekomen → actie om het in Planon te bekijken.

Staat Cyberdeck niet open, dan bewaart de extensie de rapporten (max. 20) tot Cyberdeck weer opent. Onder Cyberdeck → Instellingen → Troubleshooting staat of de extensie verbonden is. Klik je in Cyberdeck op een Planon-link in een eigen actie, dan draait de eerstvolgende lijst ook als automatisch starten uit staat.

## Handmatig
- Vink de aanvragen aan die je wilt verwerken (standaard: alle).
- **Alleen controleren**: opent elke aanvraag, vergelijkt `# Hours` met From/Till en gaat terug. Er wordt niets goedgekeurd.
- **Controleren + goedkeuren** (twee keer klikken ter bevestiging): zelfde controle; alleen bij ✓ wordt op **Approve** geklikt. Bij ✗ wordt de aanvraag overgeslagen en blijft hij staan.
- **Stop** breekt de run af na de huidige stap.

## Urencontrole
- Zelfde dag: verschil tussen From en Till (bijv. 13:00–17:00 = 4u).
- Meerdaags: eerste dag vanaf From tot einde werkdag, tussenliggende werkdagen volledig, laatste dag vanaf begin werkdag tot Till. Weekenden tellen niet mee (instelbaar).
- Werkdag: **08:30–17:00 = 8 uur**, want er gaat 0,5 uur pauze af (12:30–13:00).
- De pauze gaat alleen af als het verlof over de pauze heen loopt: 13:00–17:00 = 4u, 08:30–12:30 = 4u, 08:30–17:00 = 8u, 08:30–13:00 = 4u.
- Werkdag en pauze kun je aanpassen onder *Instellingen urencontrole*.
- Extra veiligheid: de extensie controleert of de geopende aanvraag dezelfde From/Till heeft als de regel in de lijst.

## Bevestigingsstap na Approve
Getest: Planon keurt direct goed en keert terug naar de lijst (geen extra scherm); de aanvraag verdwijnt uit de lijst. Mocht Planon in de toekomst toch na Approve een extra scherm tonen (bijv. opmerking + OK/Save), wordt de knop oranje gemarkeerd en wacht de extensie tot je zelf bevestigt; daarna gaat hij verder. *Eventuele bevestigingsstap automatisch klikken* staat standaard aan (alleen als er precies één duidelijke OK/Save-knop is); zet het uit als je zelf wilt bevestigen.
