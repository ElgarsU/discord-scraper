"""One-shot cleanup: delete all Discord webhook messages for a given listing_key,
then delete those rows from the DB so the next scrape treats those ads as new.

Run on the VM (against the live DB and webhook):

    cd /opt/discord-scraper/app
    sudo -u discord-scraper /opt/discord-scraper/venv/bin/python \\
        scripts/cleanup_listing.py \\
        --listing-key ktm-exc \\
        --webhook-url 'https://discord.com/api/webhooks/.../...' \\
        --db /opt/discord-scraper/data/scraper.db

Add --dry-run to preview without touching Discord or the DB.

Note: only deletes the *original* ad messages we posted (we have those IDs in the
DB). The 'pointer' messages posted when an ad goes gone are NOT tracked, so they
will be left behind for manual cleanup.
"""

import argparse
import sqlite3
import sys
import time

import httpx


def delete_message(webhook_url: str, message_id: str, *, timeout: float = 15.0) -> str:
    """Returns one of: 'deleted', 'already-gone', 'failed:<status>'.
    Handles 429 with Retry-After (one retry)."""
    url = f"{webhook_url}/messages/{message_id}"
    response = httpx.delete(url, timeout=timeout)

    if response.status_code == 429:
        retry_after = float(response.headers.get("Retry-After", "1"))
        time.sleep(retry_after + 0.1)
        response = httpx.delete(url, timeout=timeout)

    if response.status_code == 204:
        return "deleted"
    if response.status_code == 404:
        return "already-gone"
    return f"failed:{response.status_code}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing-key", required=True)
    parser.add_argument("--webhook-url", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT id, ad_slug, discord_message_id
        FROM ads
        WHERE listing_key = ?
        ORDER BY id
        """,
        (args.listing_key,),
    ).fetchall()

    if not rows:
        print(f"no rows found for listing_key={args.listing_key!r}")
        return 0

    with_id = [r for r in rows if r["discord_message_id"]]
    without_id = [r for r in rows if not r["discord_message_id"]]
    print(
        f"found {len(rows)} rows for listing_key={args.listing_key!r} "
        f"({len(with_id)} with discord_message_id, {len(without_id)} without)"
    )
    if args.dry_run:
        for row in rows:
            print(f"  would delete: {row['ad_slug']} (msg_id={row['discord_message_id']!r})")
        print("dry-run: no changes made")
        return 0

    counts = {"deleted": 0, "already-gone": 0, "failed": 0}
    for row in with_id:
        result = delete_message(args.webhook_url, row["discord_message_id"])
        bucket = "failed" if result.startswith("failed") else result
        counts[bucket] += 1
        print(f"  {result}: {row['ad_slug']} (msg_id={row['discord_message_id']})")
        time.sleep(0.5)  # gentle pacing under Discord webhook rate limits

    connection.execute("DELETE FROM ads WHERE listing_key = ?", (args.listing_key,))
    connection.commit()
    connection.close()

    print(
        f"\nsummary: deleted={counts['deleted']} "
        f"already-gone={counts['already-gone']} failed={counts['failed']} "
        f"db_rows_removed={len(rows)}"
    )
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
