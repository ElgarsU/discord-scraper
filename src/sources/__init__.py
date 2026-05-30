"""Per-portal scraper modules. Each module exposes:

    iter_all_rows(base_url) -> Iterator[ListingRow]
    matches_filter(row, listing_config) -> bool
    fetch_ad(url) -> str
    parse_ad(html, url) -> Ad
"""

import hashlib
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
RIGA = ZoneInfo("Europe/Riga")


class ScrapeError(Exception):
    pass


class NotFoundError(ScrapeError):
    """Raised when a detail page returns 404 — usually an ad that was deleted
    after we last saw it (stale-index case where the listing still shows it)."""
    pass


@dataclass
class Ad:
    slug: str
    url: str
    make: str | None
    model: str | None
    year: int | None
    engine_cc: int | None
    price_eur: float | None
    price_display: str | None
    location: str | None
    description: str
    date_posted: datetime | None
    photos: list[str] = field(default_factory=list)
    mileage_km: int | None = None

    @property
    def hash(self) -> str:
        # When the source exposes a posted-at timestamp (ss.com), include it so
        # bumping the ad changes the hash. When it doesn't, fall back to the
        # slug — keeps the hash unique per ad while preserving
        # price-change-as-bump semantics.
        suffix = self.date_posted.isoformat() if self.date_posted else self.slug
        return hashlib.sha256(f"{self.price_eur}|{suffix}".encode()).hexdigest()

    @property
    def date_posted_display(self) -> str:
        return self.date_posted.strftime("%Y-%m-%d %H:%M") if self.date_posted else ""


@dataclass
class ListingRow:
    slug: str
    url: str
    model: str | None
    year: int | None
    engine_cc: int | None
    price_text: str | None
    region: str | None


def http_get(url: str, *, timeout: float = 15.0) -> httpx.Response:
    response = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
    if response.status_code == 404:
        raise NotFoundError(url)
    response.raise_for_status()
    return response


def download_photos(slug: str, photo_urls: list[str], images_dir: str) -> list[str]:
    """Download photos to {images_dir}/{slug}/{n}{ext}. Idempotent (skips files
    that already exist on disk). Returns relative paths (from images_dir) for
    every file present on disk after the call. Per-file errors are logged to
    stderr and skipped — the rest still succeed."""
    target_dir = Path(images_dir) / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for index, url in enumerate(photo_urls, start=1):
        ext = Path(urlparse(url).path).suffix or ".jpg"
        rel = f"{slug}/{index}{ext}"
        full = Path(images_dir) / rel
        if not full.exists():
            try:
                response = httpx.get(
                    url, headers=HEADERS, timeout=30, follow_redirects=True
                )
                response.raise_for_status()
                full.write_bytes(response.content)
            except Exception as exc:
                print(f"image download failed {url}: {exc}", file=sys.stderr)
                continue
        saved.append(rel)
    return saved
