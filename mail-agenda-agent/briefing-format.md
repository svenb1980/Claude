# Formaat van het briefing-document

De ochtendbriefing schrijft één document in de eigen opslag van Action Desk:

- **Plek:** `data/users/<jij>/agentbriefing`. Met de `ArtifactData`-tool is dat `collection: "data/users/me"` en `doc_id: "agentbriefing"`.
- **Wie kan het zien:** alleen jij. `data/users/` is per gebruiker afgeschermd, ook voor anderen met wie Action Desk gedeeld is.
- **Wanneer zichtbaar:** Action Desk toont het blok *Morning briefing* alleen op de dag in `date`. Een briefing van gisteren blijft verborgen.
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
        "link": "https://outlook.office365.com/owa/?ItemID=…"
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
        { "start": "10:30", "end": "11:00", "title": "1:1 title", "with": "1:1", "note": "", "link": "https://…" }
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
| `mail.action` | Mail die iets van jou vraagt, het belangrijkste eerst. Maximaal 12 |
| `mail.info` | Relevant maar geen actie, of al beantwoord. Maximaal 30. Staat in Action Desk ingeklapt |
| `mail.noise` | Alleen aantallen: meldingen, timecards, vergaderreacties en dergelijke |
| `days[]` | Vandaag en de volgende werkdag. `routine` = aantal standups en huddles (niet getoond). `issues` = waarschuwingen. `meetings` = niet-routine meetings met `start`/`end` als `HH:MM` lokale tijd |
| `notes` | Korte meldingen over wat niet lukte. Maximaal 4 |
| `link` | Altijd een `https://`-link, ongewijzigd uit Outlook. Andere links toont Action Desk als gewone tekst |
