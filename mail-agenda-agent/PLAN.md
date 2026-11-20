# Mail- & Agenda-agent: plan

Een agent die zelf je Outlook-mail en -agenda bijhoudt en je op het goede moment een seintje geeft.
**Action Desk** is een dashboard dat je zelf opent. Deze agent komt **naar jou toe**.

Status: Fase 0 afgerond (keuzes vastgelegd op 20-11-2026). Fase 1 in aanbouw: het blok *Morning briefing* in Action Desk is klaar, de instructies staan in `prompts/ochtendbriefing.md`.

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

## Fases

| Fase | Wat | Klaar als |
|---|---|---|
| **1. Fundament + ochtendbriefing** (week 1) | Mail-triage + agenda-bewaker, alleen lezen. Een nieuw blok "Briefing" in Action Desk | Je krijgt elke werkdag om 07:45 een bruikbare briefing. Een week bijstellen: "dit was ruis", "dit miste ik" |
| **2. Urgent-check** (week 2) | Elk uur een check op VIP's en incidenten, met geheugen van wat al gemeld is | Geen dubbele en geen onnodige meldingen gedurende een week |
| **3. Voorbereiden & concepten** (week 3) | Meeting-voorbereider (alles behalve routine) + conceptschrijver | Bij elke niet-routine meeting een brief, en concepten die je met kleine aanpassingen kunt versturen |
| **4. Opvolging & team** (week 4) | Wachten-op-lijst en toezeggingen. Team-signalen met 1-op-1-ritme per persoon. In Action Desk een instellingenblok "Agent" voor VIP's en het 1-op-1-ritme | Je ziet elke week op tijd wie een 1-op-1 tegoed heeft en wat er bij wie blijft liggen |

## Wat ik nog van je nodig heb

1. **Akkoord op pushmeldingen** van de Claude-app voor de urgent-check (Fase 2), of liever alleen Action Desk.
2. **VIP-lijst**: je leidinggevende en sleutelpersonen (Fase 2). Je vult die in bij Action Desk, niet in de repo.
3. **1-op-1-ritme per teamlid** (Fase 4). Ik vul de lijst vooraf met de mensen uit je standup-chats, jij zet het ritme erbij.
4. ~~Tijden bevestigen~~: bevestigd op 20-11-2026. Briefing om 07:45 en de uurcheck van 08:00 tot 17:00 (Europe/Amsterdam).

## Risico's en aandachtspunten

- **Niet realtime:** een urgente mail kan tot een uur blijven liggen. Is dat te traag, dan stappen we later over op de Agent SDK met Microsoft Graph-webhooks (vraagt hosting en een Azure-app).
- **Gebruik:** ongeveer 11 runs per werkdag. De uurcheck is bewust licht gehouden (alleen VIP's en incidenten).
- **Fout-positieven in de triage** in de eerste week. Daarom is week 1 vooral bijstellen.
- **Team-signalen gaan over mensen.** De toon blijft ondersteunend en de gegevens blijven alleen bij jou.
