import sys
import traceback

from src import config, db, notifier
from src.sources import NotFoundError, ScrapeError, auto24, autoplius, download_photos, ss

# mototehnika.ee runs on the same backend as auto24.ee — same HTML, same
# selectors, same image CDN. Reuses the auto24 module by alias.
SOURCES = {"ss": ss, "auto24": auto24, "mototehnika": auto24, "autoplius": autoplius}


def process_url(url: str, slug: str, listing_key: str, source, webhook_url: str) -> str:
    try:
        html = source.fetch_ad(url)
    except NotFoundError:
        return _handle_404(slug, listing_key, webhook_url)

    ad = source.parse_ad(html, url)

    if not ad.make or not ad.model or ad.price_eur is None:
        raise ScrapeError(
            f"missing required fields after parse: "
            f"make={ad.make!r} model={ad.model!r} price_eur={ad.price_eur}"
        )

    if db.hash_seen(config.DB_PATH, ad.hash, listing_key):
        return f"skip (already notified): {ad.slug}"

    kind = "bumped" if db.slug_seen(config.DB_PATH, ad.slug, listing_key) else "new"
    local_paths = download_photos(ad.slug, ad.photos, config.IMAGES_DIR)
    message_id = notifier.send_ad(webhook_url, ad, kind)
    db.insert_ad(config.DB_PATH, ad, kind, listing_key, local_paths, message_id)
    return f"notified ({kind}): {ad.slug} ({len(local_paths)}/{len(ad.photos)} images saved)"


def _handle_404(slug: str, listing_key: str, webhook_url: str) -> str:
    """Detail page is 404 but the listing index still shows the ad. If we'd
    notified it before, mark it as gone now (one-shot); if we never saw it,
    skip silently — no error notification."""
    row = db.find_latest_row(config.DB_PATH, slug, listing_key)
    if row is None:
        return f"skip (404, never notified): {slug}"
    try:
        if row["gone_notified_at"]:
            return f"skip (404, already marked gone): {slug}"
    except (IndexError, KeyError):
        pass
    result = notifier.mark_ad_gone(webhook_url, row)
    db.mark_gone(config.DB_PATH, slug, listing_key)
    return f"gone via 404 ({result}): {slug}"


def process_listing(listing_config: dict) -> bool:
    """Returns True on success, False if the listing fetch failed. Per-ad
    failures inside a successful listing don't count as a listing failure."""
    key = listing_config["key"]
    name = listing_config["name"]
    source = SOURCES[listing_config["source"]]
    webhook_url = config.webhook_url(listing_config)
    print(f"[{key}] fetching listing: {name}")

    try:
        rows = list(source.iter_all_rows(listing_config["base_url"]))
    except Exception as exc:
        print(f"[{key}] ERROR fetching listing: {exc}", file=sys.stderr)
        traceback.print_exc()
        try:
            notifier.send_error(webhook_url, exc, context=f"listing {key}")
        except Exception:
            traceback.print_exc()
        return False

    matching = [r for r in rows if source.matches_filter(r, listing_config)]
    print(f"[{key}] {len(rows)} ads on listing, {len(matching)} match filter")

    db.mark_seen_in_listing(config.DB_PATH, [r.slug for r in rows], key)

    for row in matching:
        try:
            print(f"[{key}] {process_url(row.url, row.slug, key, source, webhook_url)}")
        except Exception as exc:
            print(f"[{key}] ERROR ad {row.slug}: {exc}", file=sys.stderr)
            traceback.print_exc()
            try:
                notifier.send_error(webhook_url, exc, context=f"ad {row.url}")
            except Exception:
                traceback.print_exc()

    gone = db.find_disappeared(config.DB_PATH, [r.slug for r in rows], key)
    for row in gone:
        try:
            result = notifier.mark_ad_gone(webhook_url, row)
            db.mark_gone(config.DB_PATH, row["ad_slug"], key)
            print(f"[{key}] gone ({result}): {row['ad_slug']}")
        except Exception:
            traceback.print_exc()

    return True


def main() -> None:
    db.init_db(config.DB_PATH)
    failed = False
    for listing_config in config.LISTINGS:
        try:
            ok = process_listing(listing_config)
        except Exception as exc:
            # Truly unexpected (e.g. webhook env var missing). Use the global
            # error webhook since we can't trust the per-listing one.
            ok = False
            traceback.print_exc()
            try:
                notifier.send_error(
                    config.ERROR_WEBHOOK_URL,
                    exc,
                    context=f"listing {listing_config.get('key', '?')}",
                )
            except Exception:
                print("ALSO failed to send error notification:", file=sys.stderr)
                traceback.print_exc()
        if not ok:
            failed = True
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
