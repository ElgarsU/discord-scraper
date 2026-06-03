# CLAUDE.md — discord-scraper

> **Deployment lives in the infra repo** (`git@github.com:ElgarsU/infra.git`).
> As of 2026-06-03 the `deploy/` Ansible tree, `deploy.sh`, and `INFRA.md` were
> migrated out of here into infra (`apps/discord-scraper/`). This repo holds only
> application code + `build.sh`. To deploy: `./deploy.sh discord-scraper` from
> infra. The Discord webhook is in infra's `secrets/discord-scraper.env`.

## What it is

Python scraper for ss.com Husqvarna FE 250/350 listings → Discord. Scheduled via
a systemd timer (08:00 / 12:40 / 17:20 / 22:00 Europe/Riga), `Type=oneshot`,
local SQLite at `/opt/discord-scraper/data/scraper.db`. No web surface.

## Layout

- `src/main.py` — entry (`python -m src.main`).
- `src/config.py` — `LISTINGS` (currently only the ss.com Husqvarna FE source),
  reads `DISCORD_WEBHOOK_HUSQVARNA_FE` + `DB_PATH` from the env.
- `src/sources/ss.py` — the ss.com scraper.
- `src/db.py`, `src/notifier.py` — SQLite + Discord posting.

## Gotchas

- **Dedup hash** = `sha256(price | posted-time-or-slug)`. An ad bumped at the
  same price keeps the same hash → no re-notify. Deliberate.
- **404 handling**: a previously-notified ad whose detail page 404s is marked
  "gone" once; an ad never notified is skipped silently.
- All timestamps stored UTC; the timer fires at Riga-local times (the deploy
  sets the system timezone to Europe/Riga).
