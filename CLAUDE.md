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

Python scraper for ss.com 2-stroke enduro listings → Discord. Three sources, each
to its own channel: Husqvarna (TE/FE, 300cc) and KTM (EXC, 300cc) scraped from
per-make category pages, plus Sherco/Beta/GasGas (2-stroke, 250–300cc, 2020+)
scraped via the ss.com **search form** across all makes. Scheduled via a systemd
timer (08:00 / 12:40 / 17:20 / 22:00 Europe/Riga), `Type=oneshot`, local SQLite
at `/opt/discord-scraper/data/scraper.db`. No web surface.

## Layout

- `src/main.py` — entry (`python -m src.main`).
- `src/config.py` — `LISTINGS` (three ss.com sources: `ss-husqvarna-fe`,
  `ss-ktm-exc`, `ss-sherco-beta-gasgas`), reads `DISCORD_WEBHOOK_HUSQVARNA_FE`,
  `DISCORD_WEBHOOK_KTM_EXC`, `DISCORD_WEBHOOK_SHERCO_BETA` + `DB_PATH` from env.
- `src/sources/ss.py` — the ss.com scraper. `iter_all_rows(listing)` dispatches:
  a config with a `search` block → `_iter_search_rows` (search form); otherwise
  `_iter_category_rows` (per-make `base_url`).
- `src/db.py`, `src/notifier.py` — SQLite + Discord posting.

## Gotchas

- **Search source (`_iter_search_rows`)**: ss.com stores search criteria in a
  server-side PHP session, so the scraper must GET `.../motorcycles/search/` to
  seed a cookie jar, then POST the form to `.../motorcycles/search-result/`
  (pagination is `search-result/pageN.html` within the same `httpx.Client`).
  The make field `opt[227][]` is **omitted entirely** — sending it empty makes
  ss.com return **zero** results. cc/year come from the config `search` block
  (`cc_min`/`cc_max`/`year_min`).
- **Extra make column**: search-result rows have **5** `td.msga2-o` cells
  `[make, model, year, cc, price]` vs the **4** on category pages
  `[model, year, cc, price]`. `_parse_rows(..., has_make=True)` handles the
  offset and fills `ListingRow.make` (None on category pages).
- **Short needles need the cc filter**: the Sherco/Beta/GasGas source matches
  `se/rr/ec/gas/...` as substrings against **make+model**. These only work
  because the 250–300cc server filter first strips the superbikes (`S1000RR`),
  motocross, and look-alikes (`Hecht` mowers) they'd otherwise catch;
  `model_excludes` (`hecht`/`berreta`/`beretta`) mops up the residue. Don't
  widen the cc range without re-checking the noise.
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
