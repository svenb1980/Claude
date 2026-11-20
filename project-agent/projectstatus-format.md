# Formaat van `projectstatus`

Het document `data/users/<jij>/projectstatus` in de opslag van Cyberdeck. De projectagent schrijft het elke maandag in zijn
geheel opnieuw (`ArtifactData`, `action: "set"`). Cyberdeck leest het en toont het achter de knop **Projects**. Het vorige
document is ook het geheugen van de agent: daaruit haalt hij de trend, verschoven deadlines en statuswissels.

Alle teksten zijn Engels. Datums zijn `JJJJ-MM-DD` (lokaal, Europe/Amsterdam), tijdstempels ISO in UTC.

```json
{
  "v": 1,
  "week": "2026-W48",
  "createdAt": "2026-11-23T06:17:00Z",
  "headline": "Java 25 is red: the core item has been idle for 29 days. Event Connector is due in 4 weeks.",
  "counts": { "red": 1, "amber": 3, "green": 0 },
  "projects": [
    {
      "id": "9046982927",
      "name": "Java 25",
      "title": "Java 25 | Project Overview",
      "page": "https://planon.atlassian.net/wiki/spaces/DEV/pages/9046982927",
      "roles": ["Manager", "Manager Projects", "STEERCO Owner"],
      "lead": "Kim van Heel",
      "pm": "Jean-Luc Heideman",
      "status": { "paf": "Started", "page": "NEW" },
      "phase": "Q4 2026: core migration to JDK 25 and WildFly 41, plus SecurityManager and time zone changes.",
      "rag": "red",
      "trend": "new",
      "why": "TEC-14329 in the current release has been idle for 29 days.",
      "deadline": { "date": "2026-11-30", "approx": true, "label": "L136 (Nov '26)", "source": "roadmap", "daysLeft": 7, "previous": "" },
      "release": { "current": "L136", "next": "L137" },
      "progress": { "done": 0, "total": 8, "parked": 1 },
      "done":  [ { "key": "", "summary": "", "link": "" } ],
      "moved": [ { "key": "", "summary": "", "from": "", "to": "", "link": "" } ],
      "next":  [ { "key": "TEC-14329", "summary": "JDK25 + Wildfly 41", "status": "Development", "owner": "Harsha Vardhan Sai Thirukkovalluri", "release": "L136", "idle": 29, "link": "https://planon.atlassian.net/browse/TEC-14329" } ],
      "attention": [ { "level": "red", "text": "TEC-14329 (current release L136) idle for 29 days.", "link": "https://planon.atlassian.net/browse/TEC-14329" } ],
      "openPoints": [ { "text": "Target release and end date", "owner": "Kim van Heel", "mine": false } ],
      "jira": { "jql": "key in (TEC-9010, …) OR parent in (TEC-9010, …)", "link": "https://planon.atlassian.net/issues/?jql=…" },
      "pageUpdated": "2026-11-03",
      "snapshot": { "TEC-14329": "Development" },
      "steerco": {
        "title": "Java 25",
        "manager": "Sven Burgers",
        "summary": "Core migration in development, no target release yet",
        "risk": "No target release: the core item (TEC-14329) slipped from L134 to L136; development rests on one developer.",
        "decision": { "needed": false, "text": "" },
        "progress": { "done": "", "cancelled": "", "inProgress": "JDK 25 and WildFly 41 (TEC-14329, L136)", "inTest": "",
                      "toPickUp": "Time zones without SecurityManager (TEC-14349, L136); WildFly 41 update (TEC-13735, L136)", "delayed": "" },
        "customer": { "who": "All Planon customers, cloud and on-premise, and Cloud Ops.",
                      "value": "Planon stays on a supported Java LTS and application server, with ongoing security fixes.",
                      "points": [ "Supported runtime for security questionnaires and audits", "Better monitoring through Dynatrace on the new JDK" ] }
      }
    }
  ],
  "notes": []
}
```

## Velden

| Veld | Betekenis |
|---|---|
| `week` | ISO-week van de run |
| `headline` | Eén zin, hoogstens ±110 tekens, het belangrijkste van de week |
| `counts` | Aantal projecten per kleur |
| `projects[]` | Volgorde: red, amber, green; binnen een kleur de vroegste deadline eerst |
| `id` | Pagina-id van de projectpagina (leeg als er geen pagina is) |
| `name` | Naam zoals in de PAF-tabel; zonder PAF-rij de paginatitel zonder ` \| Project Overview` |
| `roles` | `Manager` (PAF-tabel), `Manager Projects` en/of `STEERCO Owner` (Status-blok van de pagina) |
| `status.paf` / `status.page` | Status zoals de PAF-tabel en het Status-blok die noemen |
| `phase` | *Current phase* uit *At a glance*, ingekort, zonder links |
| `rag` | `red`, `amber` of `green`, volgens de vaste regels in `prompts/weekcheck.md` stap 5 |
| `trend` | `new`, `better`, `same` of `worse` ten opzichte van vorige week |
| `why` | Eén zin: het signaal dat de kleur bepaalde |
| `deadline.source` | `PAF` (End Date), `milestone` (datum in *Next milestone*), `roadmap` (eindrelease, laatste dag van die maand, `approx: true`) of `none` |
| `deadline.daysLeft` | Dagen tot de deadline; negatief als hij voorbij is |
| `deadline.previous` | De deadline van vorige week als die anders was |
| `release` | De huidige en volgende release volgens de kop van de roadmaptabel |
| `progress` | `done` en `total` tellen werk-items: de rijen van de roadmaptabel (ook als Jira ze als subtaak heeft) en hun kinderen, zonder parent-epics en zonder subtaken die geen eigen rij hebben; `parked` = items die de pagina als *not planned* of *off the plan* markeert |
| `done` | Werk-items die de afgelopen 7 dagen naar Done gingen (hoogstens 10) |
| `moved` | Statuswissels sinds vorige week (hoogstens 8) |
| `next` | Open werk-items: huidige release, dan volgende, dan de rest; `idle` = dagen sinds de laatste activiteit van het item of zijn subtaken (hoogstens 8) |
| `attention[]` | Aandachtspunten met `level` `red`, `amber` of `info` (hoogstens 8, rood eerst), elk met een link |
| `openPoints[]` | *Open points* van de pagina; `mine: true` als jij de eigenaar bent (hoogstens 6) |
| `jira.link` | Jira-zoeklink naar alle items van het project |
| `pageUpdated` | Datum van de laatste versie van de projectpagina |
| `snapshot` | Status per Jira-sleutel, voor de vergelijking volgende week. Cyberdeck toont dit niet |
| `steerco` | De teksten voor de STEERCO-slide (knop *STEERCO slides* in Cyberdeck, `js/steerco.js`): `title`, `manager`, `summary` (≤ 70), `risk` (≤ 170), `decision`, `progress` met zes regels (≤ 130: done, cancelled, inProgress, inTest, toPickUp, delayed) en `customer` (`who` ≤ 140, `value` ≤ 160, hoogstens 3 `points` ≤ 95). Regels in `prompts/weekcheck.md` stap 5b |
| `notes` | Korte zinnen over wat niet lukte, en nieuwe of vervallen projecten |

## `projectsettings`

Het document `data/users/<jij>/projectsettings`. Je bewerkt het in Cyberdeck (*Settings › Project agent*, fase 2). De agent
leest het alleen.

```json
{
  "v": 1,
  "updatedAt": "ISO UTC",
  "mappings": [
    { "name": "WEBDAV", "page": "9047048709", "epics": [] }
  ]
}
```

- `name`: de projectnaam zoals in de PAF-tabel.
- `page`: het pagina-id van de projectpagina. Nodig als de titel anders is dan `<name> | Project Overview`.
- `epics`: extra Jira-sleutels die bij het project horen maar niet in de roadmaptabel staan. Mag leeg zijn.
- `workstream` (optioneel): de werkstroom bovenaan de STEERCO-slide, bijvoorbeeld "Core Platform" (de standaard).
