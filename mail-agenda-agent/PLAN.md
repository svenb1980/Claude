# Mail- & Agenda-agent: plan

Een agent die zelf je Outlook-mail en -agenda bijhoudt en je op het goede moment een seintje geeft.
**Action Desk** is een dashboard dat je zelf opent. Deze agent komt **naar jou toe**.

Status op 20-11-2026: **Fase 1 is klaar.** Het blok *Morning briefing* draait in Cyberdeck (de huidige Action Desk). De geplande
taak *Mail- en agenda-agent – ochtendbriefing* (ma–vr 07:45) heeft de Microsoft 365-koppeling en de testrun is geslaagd: die las
65 mails en de agenda in ongeveer 1,5 minuut en schreef de briefing in Cyberdeck. Eén run kost ongeveer $1,60. Fase 2 (de
urgent-check van elk uur) moet daarom veel lichter zijn: alleen nieuwe mail sinds de vorige check, en alleen VIP's en incidenten.

**Fase 2 draait sinds 20-11-2026.** De instructies staan in `prompts/urgent-check.md`. Cyberdeck toont de urgente meldingen van
vandaag in rood bovenaan het Briefing-blok. De geplande taak *Mail- en agenda-agent – urgent-check* (ma–vr 08:31–16:31, elk uur,
met pushmelding) heeft de Microsoft 365-koppeling. Een pushmelding komt alleen bij iets urgents; bij "Niets urgents." blijft het
stil (getest). Op het standaardmodel kostte een check ongeveer $0,33, daarom draait de urgent-check sinds 20-11-2026 op
**Claude Haiku**: de testrun daarmee duurde 16 seconden en kostte ongeveer $0,01, dus zo'n $0,10 per werkdag. De ochtendbriefing
blijft op het standaardmodel (ongeveer $1,60 per run). De VIP-lijst (2 personen) staat in het document
`agentsettings` in Cyberdeck, niet in de repo.

---

## Vastgelegde keuzes

| Onderwerp | Keuze |
|---|---|
| Functies | Mail-triage · Agenda & voorbereiding · Opvolging bewaken · Team-signalen |
| Autonomie | **Concepten klaarzetten.** De agent leest alles en zet antwoorden en tijdvoorstellen als concept in Outlook. Versturen doe je zelf |
| Ritme | Op werkdagen een **ochtendbriefing** (07:45). Daarna **elk uur een urgent-check** die alleen iets meldt als het urgent is |
| Kanaal | **Action Desk**. Teams is geschrapt omdat het te veel opzetwerk was (20-11-2026). Voorstel voor de urgent-check: een **pushmelding van de Claude-app** op je telefoon, zonder extra werk voor jou |
| Urgent = | Mail van je **leidinggevende of VIP's**, en **incidenten/escalaties** (productie, klant, "urgent", "blocker", "P1") |
| 1-op-1-ritme | **Per persoon** in te stellen |
| Meetingprep | **Alle meetings behalve routine** (geen standups, huddles of terugkerende teamoverleggen) |

## Wat de koppelingen toestaan (gecontroleerd)

- **Microsoft 365**: mail lezen en schrijven (concepten), agenda lezen en schrijven, gedeelde agenda's lezen, Teams-chats **alleen lezen**.
  De agent stuurt dus geen Teams-berichten.
- **Atlassian**: Jira en Confluence lezen, voor de context bij mails en meetings (FRC, FCN, TEC, DBM).
- **Action Desk**: heeft al een eigen opslag per gebruiker en standup-chats per team. De agent zet zijn bevindingen daar neer
  en gebruikt dezelfde teamindeling.

---

## Het team

| Rol | Draait bij | Kijkt naar | Levert |
|---|---|---|---|
| 🧭 **Coördinator** | Elke run | Tijdstip, wat al gemeld is | Start de juiste rollen, voegt samen, bepaalt wat nu gemeld wordt en wat in de volgende briefing komt |
| 📥 **Mail-triage** | Briefing + uurcheck | Nieuwe mail sinds de vorige run | Deelt in als *actie nodig / ter info / wachten op / ruis*, met deadline, vraag en Jira-sleutels. De uurcheck kijkt alleen naar VIP's en incidenten |
| 📅 **Agenda-bewaker** | Briefing | Agenda vandaag en morgen | Conflicten, onbeantwoorde uitnodigingen, meetings zonder agenda, dagen zonder pauze of focustijd |
| 📋 **Meeting-voorbereider** | Briefing | Niet-routine meetings van vandaag | Korte brief per meeting: doel, deelnemers, bijbehorende mails, Jira-issues en Confluence-pagina's |
| ✍️ **Conceptschrijver** | Briefing + uurcheck | Mails met een directe vraag aan jou | Concept in je Outlook-map *Concepten*, in de taal van de afzender en in jouw toon: warm en to the point. **Verstuurt nooit zelf** |
| 🔁 **Opvolger** | Briefing | Verstuurde mail en toezeggingen | Lijst van wie jou nog iets moet leveren en wat jij hebt toegezegd, met een seintje als iets over de termijn gaat |
| 🤝 **Team-signalen** | Briefing | Je agenda, standup-chats, mail van teamleden | 1-op-1's die achterlopen op het ritme per persoon, verlof en ziekmeldingen, mails van je mensen die te lang blijven liggen |
| 📣 **Verslaggever** | Elke run | Uitkomst van de coördinator | Briefing en items in Action Desk, elk met een link naar de bron. Bij iets urgents ook een pushmelding van de Claude-app (voorstel) |

---

## Hoe het draait

```
OCHTENDBRIEFING (geplande taak, ma–vr 07:45)
  Coördinator
    ├─ Mail-triage           ┐
    ├─ Agenda-bewaker        │
    ├─ Meeting-voorbereider  ├─ parallel ─► samenvoegen ─► Conceptschrijver ─► Verslaggever
    ├─ Opvolger              │
    └─ Team-signalen         ┘

URGENT-CHECK (geplande taak, ma–vr elk uur 08–17)
  Coördinator ─► Mail-triage (alleen VIP's + incidenten)
    ├─ niets nieuws ─► stil, geen bericht
    └─ wel iets     ─► Conceptschrijver ─► Verslaggever

VERSLAGGEVER ─► Action Desk (eigen opslag, ook het geheugen:
             │  wat al gemeld is, de wachten-op-lijst, 1-op-1-historie)
             └► Pushmelding Claude-app (alleen bij iets urgents, voorstel)
```

- **Platform:** geplande Claude-taken in de cloud, met de Microsoft 365- en Atlassian-connectors. Geen eigen hosting en geen Azure-app.
  Extra netwerktoegang is ook niet nodig, dus het draait in je standaard cloud-omgeving.
- **Instructies:** de prompts per rol staan in deze map (`prompts/`), zodat je ze kunt lezen en bijstellen.
- **Geheugen tussen runs:** in de opslag van Action Desk. Zo meldt de agent niets twee keer en loopt de wachten-op-lijst door.

## Spelregels

1. **Nooit versturen.** Alleen concepten in Outlook. Uitnodigingen niet accepteren of weigeren: de agent doet alleen een voorstel.
2. **Stil als er niets is.** De uurcheck stuurt alleen een bericht bij iets urgents, en nooit twee keer hetzelfde.
3. **Altijd de bron erbij.** Elke melding linkt naar de mail, meeting, het Jira-issue of de Confluence-pagina.
4. **Persoonsgegevens niet in deze repo.** VIP's, het 1-op-1-ritme, verlof en ziekmeldingen staan alleen in de opslag van Action Desk.
5. **Team-signalen zijn voor jou, ter ondersteuning.** Alleen op basis van je eigen mailbox, agenda en de standup-chats waar je in zit.
   Geen oordeel over mensen, alleen "hier kun je iets betekenen".

---

**Fase 3 in test (20-11-2026):** de ochtendbriefing bereidt nu ook de niet-routine meetings van vandaag voor (doel,
gerelateerde mail, Jira, open punten) en zet hoogstens 5 conceptantwoorden klaar in Outlook (*Concepten*). Cyberdeck toont
*Prep* onder de meeting en *Draft ready* bij de mail. Voor de status van Jira-issues heeft de ochtendbriefing de
Atlassian-koppeling nodig. **Sinds 20-11-2026 zoekt de conceptschrijver eerst zelf op** wat een antwoord nodig heeft: in
eerdere (ook verzonden) mail, op SharePoint/OneDrive en in Confluence en Jira. Wat hij vindt, vult hij in. Wat hij niet
vindt, blijft een invulplek tussen rechte haken. Besluiten laat hij altijd aan jou. Onder *Draft ready* staat in één zin wat
hij heeft opgezocht en wat nog openstaat. Dit maakt een briefing iets duurder (geschat $2,50–3 per run).

**Fase 4 in test (20-11-2026):** de ochtendbriefing heeft een stap *Je team* (instructies stap 7). Cyberdeck toont die als
kolom *Your team* met drie onderdelen:
- **1:1s:** wie achterloopt op het 1-op-1-ritme, of bij wie de volgende 1-op-1 te laat gepland staat. Dit verschijnt alleen
  vlak voor of na de uiterste datum. De agent zoekt per persoon de 1-op-1's in je agenda (afspraken met je voornaam in de
  titel en alleen die persoon erbij).
- **Waiting on your reply:** mail van je mensen die twee werkdagen of langer onbeantwoord is. De agent onthoudt die via de
  vorige briefing, dus dit kost weinig extra.
- **Your promises:** je eigen toezeggingen uit verzonden mail van de afgelopen 10 dagen die nog openstaan.

De lijst met je mensen en hun ritme staat in `agentsettings` (`people`), niet in de repo. Claude vulde die vooraf uit je agenda:
3 personen wekelijks, 2 om de 2 weken, 1 om de 4 weken en 1 om de 6 weken. Aanpassen doe je in Cyberdeck onder
*Settings › Mail agent*; daar staan ook de VIP's. Met één klik voeg je je directe medewerkers uit *People* toe, zonder vast ritme.
Verlof en ziekte deed Cyberdeck al (`team.js`), dus de agent doet daar niets mee.

## Overlap met Cyberdeck

De live Action Desk heet nu **Cyberdeck** en kan al veel zolang je hem open hebt: mail laten triëren door Claude, een kolom
*Waiting on others*, directe medewerkers met verlof en verjaardagen, transcripts omzetten in acties, en scripts als
`prep.js` en `rhythm.js`. De agent voegt vooral toe wat ook zonder open scherm moet gebeuren: de briefing om 07:45, de
urgent-check met pushmelding en concepten in Outlook. **Bekeken op 20-11-2026:** `prep.js` toont vanaf 30 minuten voor een
kleine meeting (1–8 personen) wat er openstaat met die mensen; de agent voegt daar 's ochtends een brief per meeting aan toe.
Ask Claude maakt concepten op jouw klik; de agent zet ze vooraf klaar. `waiting.js` doet *Waiting on others* al: de
**Opvolger uit Fase 4 vervalt** daarom, op toezeggingen van jezelf na. `rhythm.js` gaat over focustijd en wrap-up, niet over
het 1-op-1-ritme; dat blijft voor Fase 4.

## Fases

| Fase | Wat | Klaar als |
|---|---|---|
| **1. Fundament + ochtendbriefing** (week 1) | Mail-triage + agenda-bewaker, alleen lezen. Een nieuw blok "Briefing" in Action Desk | Je krijgt elke werkdag om 07:45 een bruikbare briefing. Een week bijstellen: "dit was ruis", "dit miste ik" |
| **2. Urgent-check** (week 2) | Elk uur een check op VIP's en incidenten, met geheugen van wat al gemeld is | Geen dubbele en geen onnodige meldingen gedurende een week |
| **3. Voorbereiden & concepten** (week 3) | Meeting-voorbereider (alles behalve routine) + conceptschrijver | Bij elke niet-routine meeting een brief, en concepten die je met kleine aanpassingen kunt versturen |
| **4. Opvolging & team** (week 4) | Wachten-op-lijst en toezeggingen. Team-signalen met 1-op-1-ritme per persoon. In Action Desk een instellingenblok "Agent" voor VIP's en het 1-op-1-ritme | Je ziet elke week op tijd wie een 1-op-1 tegoed heeft en wat er bij wie blijft liggen |

## Wat ik nog van je nodig heb

1. ~~Akkoord op pushmeldingen~~: akkoord op 20-11-2026, voor de urgent-check (Fase 2).
2. ~~Microsoft 365-koppeling op de geplande taak~~: aangezet op 20-11-2026, testrun geslaagd.
3. ~~VIP-lijst~~: twee personen, op 20-11-2026 in Cyberdeck gezet (`agentsettings`). Aanpassen? Vraag het Claude.
4. ~~1-op-1-ritme per teamlid~~: op 20-11-2026 vooraf ingevuld uit je agenda (7 personen). Controleren en aanvullen in
   Cyberdeck, *Settings › Mail agent*.
5. ~~Tijden bevestigen~~: bevestigd op 20-11-2026. Briefing om 07:45 en de uurcheck van 08:00 tot 17:00 (Europe/Amsterdam).

## Risico's en aandachtspunten

- **Niet realtime:** een urgente mail kan tot een uur blijven liggen. Is dat te traag, dan stappen we later over op de Agent SDK met Microsoft Graph-webhooks (vraagt hosting en een Azure-app).
- **Gebruik:** ongeveer 11 runs per werkdag. De uurcheck is bewust licht gehouden (alleen VIP's en incidenten).
- **Fout-positieven in de triage** in de eerste week. Daarom is week 1 vooral bijstellen.
- **Team-signalen gaan over mensen.** De toon blijft ondersteunend en de gegevens blijven alleen bij jou.
