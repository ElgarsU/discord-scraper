# CLAUDE.md — discord-scraper

> **Deployment lives in the infra repo** (`git@github.com:ElgarsU/infra.git`).
> As of 2026-06-03 the `deploy/` Ansible tree, `deploy.sh`, and `INFRA.md` were
> migrated out of here into infra (`apps/discord-scraper/`). This repo holds only
> application code + `build.sh`. To deploy: **`git pull` the infra repo first**
> (deploys run from the local infra checkout — a stale checkout ships stale
> config), then `./deploy.sh discord-scraper` from infra. Also push this repo to
> `main` beforehand — the deploy clones `main`. The Discord webhooks are in
> infra's `secrets/discord-scraper.env`.

## What it is

Python scraper for ss.com 2-stroke enduro listings → Discord. Two sources, each
to its own channel: Husqvarna (TE/FE, 300cc) and KTM (EXC, 300cc). Scheduled via
a systemd timer (08:00 / 12:40 / 17:20 / 22:00 Europe/Riga), `Type=oneshot`,
local SQLite at `/opt/discord-scraper/data/scraper.db`. No web surface.

## Layout

- `src/main.py` — entry (`python -m src.main`).
- `src/config.py` — `LISTINGS` (two ss.com sources: `ss-husqvarna-fe` and
  `ss-ktm-exc`), reads `DISCORD_WEBHOOK_HUSQVARNA_FE`,
  `DISCORD_WEBHOOK_KTM_EXC` + `DB_PATH` from the env.
- `src/sources/ss.py` — the ss.com scraper.
- `src/db.py`, `src/notifier.py` — SQLite + Discord posting.

## Gotchas

- **Filters**: model + engine-cc are matched independently (`matches_filter`).
  The **cc filter is what pins each source to the 2-stroke** (300 only); the
  extra model names (`fe` on the Husky, `exc-f`/`excf` on the KTM) are kept only
  to catch ads sellers mislabel — they're redundant under substring matching.
- **Stale `key`**: the Husqvarna listing's `key` is still `ss-husqvarna-fe`
  though it now targets the TE 300. Don't rename it — the key ties rows to the
  dedup history in the DB; changing it orphans every past ad and re-notifies.
- **Dedup hash** = `sha256(price | posted-time-or-slug)`. An ad bumped at the
  same price keeps the same hash → no re-notify. Deliberate.
- **404 handling**: a previously-notified ad whose detail page 404s is marked
  "gone" once; an ad never notified is skipped silently.
- All timestamps stored UTC; the timer fires at Riga-local times (the deploy
  sets the system timezone to Europe/Riga).
