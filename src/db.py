import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src.sources import Ad

SCHEMA = """
CREATE TABLE IF NOT EXISTS ads (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_key              TEXT,
  ad_slug                  TEXT NOT NULL,
  ad_url                   TEXT NOT NULL,
  hash                     TEXT NOT NULL,
  make                     TEXT,
  model                    TEXT,
  year                     INTEGER,
  engine_cc                INTEGER,
  price_eur                REAL,
  price_display            TEXT,
  location                 TEXT,
  description              TEXT,
  date_posted              TEXT,
  mileage_km               INTEGER,
  photo_urls               TEXT,
  local_image_paths        TEXT,
  first_seen_at            TEXT NOT NULL,
  last_seen_at             TEXT NOT NULL,
  last_seen_in_listing_at  TEXT,
  notified_at              TEXT NOT NULL,
  notification_kind        TEXT,
  discord_message_id       TEXT,
  gone_notified_at         TEXT,
  UNIQUE(hash, listing_key)
);
CREATE INDEX IF NOT EXISTS idx_ads_slug ON ads(ad_slug);
CREATE INDEX IF NOT EXISTS idx_ads_listing ON ads(listing_key);
"""


@contextmanager
def _conn(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(db_path: str) -> None:
    with _conn(db_path) as c:
        c.executescript(SCHEMA)


def hash_seen(db_path: str, ad_hash: str, listing_key: str) -> bool:
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT 1 FROM ads WHERE hash = ? AND listing_key = ? LIMIT 1",
            (ad_hash, listing_key),
        ).fetchone()
        return row is not None


def slug_seen(db_path: str, slug: str, listing_key: str) -> bool:
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT 1 FROM ads WHERE ad_slug = ? AND listing_key = ? LIMIT 1",
            (slug, listing_key),
        ).fetchone()
        return row is not None


def find_latest_row(db_path: str, slug: str, listing_key: str) -> sqlite3.Row | None:
    """Returns the most-recent row for (slug, listing_key), or None."""
    with _conn(db_path) as c:
        return c.execute(
            """
            SELECT * FROM ads
            WHERE ad_slug = ? AND listing_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (slug, listing_key),
        ).fetchone()


def insert_ad(
    db_path: str,
    ad: Ad,
    kind: str,
    listing_key: str,
    local_image_paths: list[str],
    discord_message_id: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as c:
        c.execute(
            """
            INSERT INTO ads (
                listing_key, ad_slug, ad_url, hash, make, model, year, engine_cc,
                price_eur, price_display, location, description, date_posted,
                mileage_km, photo_urls, local_image_paths, first_seen_at,
                last_seen_at, last_seen_in_listing_at, notified_at,
                notification_kind, discord_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing_key,
                ad.slug,
                ad.url,
                ad.hash,
                ad.make,
                ad.model,
                ad.year,
                ad.engine_cc,
                ad.price_eur,
                ad.price_display,
                ad.location,
                ad.description,
                ad.date_posted.isoformat() if ad.date_posted else None,
                ad.mileage_km,
                json.dumps(ad.photos),
                json.dumps(local_image_paths),
                now,
                now,
                now,
                now,
                kind,
                discord_message_id,
            ),
        )


def mark_seen_in_listing(db_path: str, slugs: list[str], listing_key: str) -> None:
    if not slugs:
        return
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" * len(slugs))
    with _conn(db_path) as c:
        c.execute(
            f"""
            UPDATE ads SET last_seen_in_listing_at = ?
            WHERE listing_key = ? AND ad_slug IN ({placeholders})
            """,
            (now, listing_key, *slugs),
        )


def find_disappeared(
    db_path: str, current_slugs: list[str], listing_key: str
) -> list[sqlite3.Row]:
    """Latest row per slug for a listing where the ad is not in current_slugs and
    has not yet been notified as gone."""
    where_not_in = ""
    params: list = [listing_key, listing_key]
    if current_slugs:
        placeholders = ",".join("?" * len(current_slugs))
        where_not_in = f"AND ad_slug NOT IN ({placeholders})"
        params.extend(current_slugs)
    with _conn(db_path) as c:
        return c.execute(
            f"""
            SELECT * FROM ads
            WHERE listing_key = ?
              AND id IN (SELECT MAX(id) FROM ads WHERE listing_key = ? GROUP BY ad_slug)
              AND gone_notified_at IS NULL
              {where_not_in}
            """,
            tuple(params),
        ).fetchall()


def mark_gone(db_path: str, slug: str, listing_key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as c:
        c.execute(
            "UPDATE ads SET gone_notified_at = ? WHERE listing_key = ? AND ad_slug = ?",
            (now, listing_key, slug),
        )
