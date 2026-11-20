# Formaat van het briefing-document

De ochtendbriefing schrijft één document in de eigen opslag van Cyberdeck (de huidige Action Desk):

- **Plek:** `data/users/<jij>/agentbriefing`. Met de `ArtifactData`-tool is dat `collection: "data/users/me"` en `doc_id: "agentbriefing"`.
- **Wie kan het zien:** alleen jij. `data/users/` is per gebruiker afgeschermd, ook voor anderen met wie Action Desk gedeeld is.
- **Wanneer zichtbaar:** Cyberdeck toont het blok *Morning briefing* bovenaan *Your actions*, alleen op de dag in `date`. Een briefing van gisteren blijft verborgen.
- **Overschrijven:** elke run vervangt het hele document (`set`). Er is geen geschiedenis.

Alle teksten zijn in het **Engels**, net als de rest van Action Desk.

```json
{
  "v": 1,
  "date": "2026-11-23",
  "createdAt": "2026-11-23T06:45:30Z",
  "headline": "Busy Monday: two 1:1s, a planning that clashes with standups, and one approval waiting.",
  "mail": {
    "since": "2026-11-20T06:45:00Z",
    "action": [
      {
        "title": "Budget sign-off Q4",
        "from": "Display Name",
        "when": "2026-11-22T18:02:00Z",
        "why": "Asks you to sign off the Q4 budget.",
        "deadline": "due Wed",
        "link": "https://outlook.office365.com/owa/?ItemID=…",
        "draft": { "link": "https://outlook.office365.com/owa/?ItemID=…" }
      }
    ],
    "info": [
      { "title": "Sick note", "from": "Display Name", "when": "…", "why": "You already replied.", "link": "https://…" }
    ],
    "noise": {
      "count": 17,
      "groups": [ { "label": "timecards", "count": 8 }, { "label": "system alerts", "count": 5 } ]
    }
  },
  "days": [
    {
      "date": "2026-11-23",
      "label": "Today",
      "routine": 5,
      "issues": [ { "text": "Database Planning (09:00) overlaps Standup core and Daily Huddle.", "link": "https://…" } ],
      "meetings": [
        { "start": "10:30", "end": "11:00", "title": "1:1 title", "with": "1:1", "note": "", "link": "https://…" },
        { "start": "13:30", "end": "14:30", "title": "OneVoice feedback", "with": "7 people, you organise", "link": "https://…",
          "prep": { "goal": "Reflect on the OneVoice results and agree on follow-up actions.",
                    "mails": [ { "title": "OneVoice results", "from": "Display Name", "when": "…", "link": "https://…" } ],
                    "jira": [ { "key": "FCN-3013", "summary": "…", "status": "In Progress", "link": "https://…/browse/FCN-3013" } ],
                    "points": [ "Who owns the follow-up actions?" ] } }
      ]
    },
    { "date": "2026-11-24", "label": "Tomorrow", "routine": 5, "issues": [], "meetings": [] }
  ],
  "notes": [ "Calendar for tomorrow could not be read; try Refresh in Outlook." ]
}
```

| Veld | Betekenis |
|---|---|
| `date` | Lokale datum (Europe/Amsterdam) waar de briefing voor is, `JJJJ-MM-DD` |
| `createdAt` | Moment van schrijven, ISO in UTC |
| `headline` | Eén zin van maximaal ongeveer 110 tekens: het belangrijkste van de dag |
| `mail.since` | Begin van het mailvenster (vorige werkdag 07:45 lokaal) |
| `mail.action` | Mail die iets van jou vraagt, het belangrijkste eerst. Maximaal 12. `draft.link` wijst naar het conceptantwoord dat de agent in je Outlook-map *Concepten* zette (`existing: true` als dat er al stond). Cyberdeck toont dan *Draft ready* |
| `mail.info` | Relevant maar geen actie, of al beantwoord. Maximaal 30. Staat in Action Desk ingeklapt |
| `mail.noise` | Alleen aantallen: meldingen, timecards, vergaderreacties en dergelijke |
| `days[]` | Vandaag en de volgende werkdag. `routine` = aantal standups en huddles (niet getoond). `issues` = waarschuwingen. `meetings` = niet-routine meetings met `start`/`end` als `HH:MM` lokale tijd |
| `meetings[].prep` | Alleen voor vandaag, bij niet-routine meetings met minstens twee andere deelnemers (maximaal 4): `goal` (doel uit de uitnodiging), `mails` (maximaal 3 gerelateerde mails van de afgelopen 14 dagen), `jira` (maximaal 3 issues, met status als de Atlassian-koppeling er is) en `points` (maximaal 3 open punten). Cyberdeck toont het als uitklapbaar *Prep* onder de meeting |
| `notes` | Korte meldingen over wat niet lukte. Maximaal 4 |
| `link` | Altijd een `https://`-link, ongewijzigd uit Outlook. Andere links toont Cyberdeck als gewone tekst |

---

# Documenten van de urgent-check

Ook deze twee staan in de eigen opslag van Cyberdeck (`collection: "data/users/me"`), dus alleen jij kunt ze lezen.

## `agentsettings`: instellingen van de agent

```json
{ "v": 1, "vips": [ { "name": "Display Name", "email": "naam@bedrijf.nl" } ], "updatedAt": "ISO UTC" }
```

`vips` zijn de mensen van wie elke mail meteen gemeld wordt: je leidinggevende en andere sleutelpersonen. Claude vult de lijst
op jouw verzoek. Deze persoonsgegevens staan bewust niet in de repo.

## `agenturgent`: geheugen en meldingen

```json
{
  "v": 1,
  "lastCheck": "2026-11-20T13:31:05Z",
  "seen": [ "<internetMessageId>" ],
  "alerts": [
    { "id": "<internetMessageId>", "at": "2026-11-20T13:31:05Z", "when": "2026-11-20T13:12:40Z", "title": "Production down at customer X",
      "from": "Display Name", "kind": "incident", "why": "Asks you to free up a developer today.", "link": "https://outlook.office365.com/…" }
  ]
}
```

| Veld | Betekenis |
|---|---|
| `lastCheck` | Moment van de laatste zoekopdracht. De volgende check begint 10 minuten eerder, om niets te missen |
| `seen` | Mails die rond `lastCheck` al bekeken zijn, zodat die overlap niet dubbel gemeld wordt |
| `alerts` | Urgente meldingen van de afgelopen 3 dagen, nieuwste eerst, maximaal 20. `kind` is `vip` of `incident` |

Cyberdeck toont de meldingen van **vandaag** in rood bovenaan het blok *Morning briefing*, ook als het blok is ingeklapt. Onderaan
staat het tijdstip van de laatste check.
