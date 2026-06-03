# discord-scraper

Python scraper that polls **ss.com** for Husqvarna FE 250/350 listings,
deduplicates (price + posted-time hash), archives photos, and posts
new/bumped/gone notifications to a Discord webhook. Runs as a scheduled
`systemd` timer (4×/day, Europe/Riga); no web surface, local SQLite state.

## Run locally

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env        # set DISCORD_WEBHOOK_HUSQVARNA_FE
./.venv/bin/python -m src.main
```

## Deployment

Deployment is handled by the **infra** repo: `git@github.com:ElgarsU/infra.git`.
This repo contains only application code + `build.sh`. No Ansible, no deploy
scripts, no secrets live here.

- `build.sh` stages the source into `dist/`; infra builds the venv + installs
  the systemd service/timer on the VPS.
- To deploy, from the infra repo: `./deploy.sh discord-scraper`.
- The Discord webhook lives in infra's `secrets/discord-scraper.env` (it was
  previously kept in the deploy tree — now centralized).

See the infra repo for VPS architecture and conventions.
