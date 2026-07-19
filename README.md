# discord-scraper

Python scraper that polls **ss.com** for 2-stroke enduro listings,
deduplicates (price + posted-time hash), archives photos, and posts
new/bumped/gone notifications to Discord. Runs as a scheduled `systemd`
timer (4×/day, Europe/Riga); no web surface, local SQLite state.

Three channels, each its own webhook:

- **Husqvarna TE 300** and **KTM EXC 300** — scraped from the per-make
  category pages (make pinned by URL, filtered to 300cc).
- **Sherco / Beta / GasGas 2-stroke (250–300cc, 2020+)** — driven by the
  ss.com **search form** across all makes. The server does the coarse cut
  (year ≥ 2020, 250–300cc); a client-side make+model needle match then keeps
  the target brands. See `src/sources/ss.py` (`_iter_search_rows`).

## Run locally

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env        # set the three DISCORD_WEBHOOK_* vars
./.venv/bin/python -m src.main
```

## Deployment

Deployment is handled by the **infra** repo: `git@github.com:ElgarsU/infra.git`.
This repo contains only application code + `build.sh`. No Ansible, no deploy
scripts, no secrets live here.

- `build.sh` stages the source into `dist/`; infra builds the venv + installs
  the systemd service/timer on the VPS.
- To deploy, from the infra repo — **always `git pull` infra first** (deploys run
  from the local infra checkout, so a stale checkout ships stale config), then:
  ```bash
  git -C ~/dev/infra pull --ff-only && (cd ~/dev/infra && ./deploy.sh discord-scraper)
  ```
  Also push this repo's changes to `main` first — the deploy clones `main`.
- The Discord webhooks live in infra's `secrets/discord-scraper.env` (it was
  previously kept in the deploy tree — now centralized). Adding a channel means
  adding its `DISCORD_WEBHOOK_*` line there before deploying — e.g.
  `DISCORD_WEBHOOK_SHERCO_BETA` for the Sherco/Beta/GasGas channel.

See the infra repo for VPS architecture and conventions.
