# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Contents

This is a scratch/personal project directory containing three standalone files:

| File | Description |
|---|---|
| `tictactoe.html` | Browser-based two-player Tic Tac Toe with score tracking |
| `banana-quest.html` | Top-down Zelda-style HTML5 Canvas game (banana protagonist, apple enemies) |
| `toilet-display.yaml` | ESPHome config for an ESP32 + Waveshare 1.54" e-ink toilet occupancy display |

## Git Workflow

After every change to any file in this repository, commit and push to GitHub:

```bash
git add <changed-files>
git commit -m "short description of change"
git push
```

If the repo is not yet initialised locally:
```bash
git init
git remote add origin <repo-url>
git push -u origin main
```

## Running the Web Files

No build step. Open directly in a browser:

```bash
start tictactoe.html
start banana-quest.html
```

## ESPHome (toilet-display.yaml)

Flash to device:
```bash
esphome run toilet-display.yaml
```

Validate config without flashing:
```bash
esphome config toilet-display.yaml
```

Requires a `secrets.yaml` alongside the file with: `wifi_ssid`, `wifi_password`, `api_encryption_key`, `ota_password`.

The `ha_entity_id` substitution at the top of `toilet-display.yaml` must be set to the actual Home Assistant entity (e.g. `light.toilet`).

## Architecture Notes

### banana-quest.html
Single-file game. All logic is inline `<script>`. Key classes:
- `Player` — banana character; reads `keys` map, owns a `Sword`, calls `drawHUD()`
- `Enemy` — apple AI with three states: `wander → chase → attack`; owns a `Sword`
- `Sword` — shared by player and enemies; swing arc stored as start/end angle, progress driven by `swingTimer`
- World is pre-rendered once onto an offscreen canvas (`offscreen`) at startup via `generateWorld()`, then blitted each frame with `ctx.drawImage` for performance
- Camera clamps to world bounds; entities are Y-sorted before drawing for correct overlap

### toilet-display.yaml
ESP32 deep-sleeps between cycles (`sleep_duration`). On wake it connects to WiFi, the ESPHome native API syncs the HA entity state into `toilet_state` (a `text_sensor`), the `on_value` callback checks RTC-persistent `last_state` global and only calls `id(eink).update()` when the state actually changed — avoiding unnecessary e-ink refreshes. Wake is triggered by GPIO33 (`wakeup_pin`) or the `sleep_duration` fallback timer.
