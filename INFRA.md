# Discord Scraper — Infrastructure

Hosted on a Hetzner Ubuntu VM, shared with other apps. This service is **outbound-only**: a systemd timer fires a oneshot Python job 4×/day, which scrapes a target site and posts results to a Discord webhook. No inbound ports, no DNS, no reverse proxy.

## VM

- **Host:** `89.167.98.246` (Hetzner)
- **OS:** Ubuntu
- **SSH user:** `root`

No firewall changes required — only outbound HTTPS (443) to the target site and `discord.com`.

## What gets installed on the VM

The Ansible playbook (`deploy/playbook.yml`) provisions:

- System packages: `python3`, `python3-venv`, `python3-pip`, `rsync`, `sqlite3`
- System timezone set to `Europe/Riga` (so the timer fires at the right local time)
- Unprivileged system user `discord-scraper`
- App at `/opt/discord-scraper/app` (rsync'd from this repo)
- Python venv at `/opt/discord-scraper/venv`
- Data directory at `/opt/discord-scraper/data` (owned by `discord-scraper`, `0750`) — holds the SQLite DB, persists across deploys
- `.env` at `/opt/discord-scraper/app/.env` (mode `0600`, owned by `discord-scraper`)
- `discord-scraper.service` — `Type=oneshot`, runs `python -m src.main`
- `discord-scraper.timer` — fires at **08:00, 12:40, 17:20, 22:00** local time

## Prerequisites on your Mac

```bash
brew install ansible
ansible-galaxy collection install community.general ansible.posix
```

## Secrets

Webhook URL lives in `deploy/secrets.yml` (gitignored). Template is `deploy/secrets.yml.example`.

## Deploy

```bash
cd deploy
ansible-playbook playbook.yml
```

The playbook is idempotent — re-run it after any code change to push updates.

## Verify on the VM

```bash
# Trigger a manual run (sends a Discord message immediately)
ssh root@89.167.98.246 'systemctl start discord-scraper.service'

# Check the last run
ssh root@89.167.98.246 'systemctl status discord-scraper.service'

# Tail logs
ssh root@89.167.98.246 'journalctl -u discord-scraper.service -n 50 --no-pager'

# Confirm timer is scheduled
ssh root@89.167.98.246 'systemctl list-timers discord-scraper.timer'
```

## Changing the schedule

Edit `deploy/templates/discord-scraper.timer.j2`, then re-run the playbook. The timer reload is handled by the playbook's handler.

## Persistent data

Everything the app accumulates lives under **`/opt/discord-scraper/data/`** (owned by `discord-scraper`). Survives VPS restarts and code redeploys — `rsync --delete` only touches `/opt/discord-scraper/app/`, never `data/`.

Layout:

- `data/scraper.db` — SQLite database (schema created on first run)
- `data/images/<ad_slug>/<n>.{jpg,…}` — original-size photos archived per ad on first sight (idempotent; existing files are not re-downloaded)

The DB stores **both** the original `photo_urls` (from ss.com — likely 404 after the ad expires) and `local_image_paths` (relative to `data/images/`, always-available local copies).

### Inspect on the VM

```bash
# Schema
ssh root@89.167.98.246 'sqlite3 /opt/discord-scraper/data/scraper.db ".schema"'

# List tables
ssh root@89.167.98.246 'sqlite3 /opt/discord-scraper/data/scraper.db ".tables"'

# Ad-hoc query (example — replace with real table name once schema exists)
ssh root@89.167.98.246 'sqlite3 -header -column /opt/discord-scraper/data/scraper.db "SELECT COUNT(*) FROM ads;"'

# Interactive shell
ssh root@89.167.98.246 'sqlite3 /opt/discord-scraper/data/scraper.db'
```

### Pull the DB to your Mac for analysis

```bash
scp root@89.167.98.246:/opt/discord-scraper/data/scraper.db ./scraper-$(date +%Y%m%d).db
```

Then open it locally with `sqlite3`, DB Browser for SQLite, DataGrip, etc.

### Pull archived images to your Mac

```bash
rsync -avz root@89.167.98.246:/opt/discord-scraper/data/images/ ./images/
```

Or grab the photos for a single ad:

```bash
scp -r root@89.167.98.246:/opt/discord-scraper/data/images/<ad_slug>/ ./
```

Cross-reference with SQL: `SELECT ad_slug, local_image_paths FROM ads WHERE …`

### Reset state (full re-notification)

If you ever want to wipe dedup state and re-notify all currently-listed ads on the next run:

```bash
ssh root@89.167.98.246 'systemctl stop discord-scraper.timer && rm /opt/discord-scraper/data/scraper.db && systemctl start discord-scraper.timer'
```
