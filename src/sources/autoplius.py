"""autoplius.lt scraper.

Notes:
- Detail pages return 403 to plain User-Agent requests; listing pages don't.
  curl_cffi with `impersonate="chrome"` covers both, so we use it everywhere.
- URL filter narrows by make + engine_capacity range. We still apply the
  client-side `model_contains` + `engine_cc_in` filter to pin exact models.
- No posted-at date is exposed on the page, so Ad.hash falls back to the slug
  (price-only would collide across ads at the same price within one listing).
"""

import re
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.sources import Ad, ListingRow, http_get_impersonate

PAGINATION_LIMIT = 30  # safety bound; current Husky listing fits in 2 pages


def _fetch(url: str) -> str:
    return http_get_impersonate(url)


def _slug_from_href(href: str) -> str:
    # /skelbimai/husqvarna-fe-250cc-krosiniai-29974145.html → "29974145"
    match = re.search(r"-(\d+)\.html?$", href)
    if match:
        return match.group(1)
    return Path(urlparse(href).path).stem


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


# ---------- listing page ----------

def _extract_card(card, base_url: str) -> ListingRow | None:
    href = card.get("href") or ""
    if "/skelbimai/" not in href or not re.search(r"-\d+\.html?$", href):
        return None
    url = urljoin(base_url, href)
    slug = _slug_from_href(href)

    # Combine title + first parameter (cc) into a string the substring filter can chew on.
    title_el = card.select_one(".announcement-title")
    title = title_el.get_text(strip=True) if title_el else ""
    params = card.select(".announcement-title-parameters .announcement-parameters span")
    cc_text = params[0].get_text(strip=True) if params else ""
    model = " ".join(p for p in (title, cc_text) if p) or None

    year = None
    region = None
    for span in card.select(".announcement-parameters-block .announcement-parameters span"):
        title_attr = span.get("title", "")
        if title_attr == "Pagaminimo data":
            # autoplius shows either "2016" or "2026-01" — keep the first 4 digits.
            text = span.get_text(strip=True)
            match = re.search(r"\d{4}", text)
            year = int(match.group()) if match else None
        elif title_attr == "Miestas":
            region = span.get_text(strip=True)

    price_el = card.select_one(".pricing-container strong")
    price_text = price_el.get_text(strip=True) if price_el else None

    return ListingRow(
        slug=slug,
        url=url,
        model=model,
        year=year,
        engine_cc=None,
        price_text=price_text,
        region=region,
    )


def _parse_rows(html: str, base_url: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", class_="announcements-list-container")
    if not container:
        return []
    out: list[ListingRow] = []
    for card in container.find_all("a", class_="announcement-item"):
        row = _extract_card(card, base_url)
        if row:
            out.append(row)
    return out


def _next_page_url(html: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("ul.paging a[rel='next'][href]")
    return urljoin(current_url, link["href"]) if link else None


def iter_all_rows(base_url: str) -> Iterator[ListingRow]:
    url = base_url
    seen_pages: set[str] = set()
    for _ in range(PAGINATION_LIMIT):
        if url in seen_pages:
            return  # defensive — pager loop
        seen_pages.add(url)
        html = _fetch(url)
        yield from _parse_rows(html, url)
        next_url = _next_page_url(html, url)
        if not next_url:
            return
        url = next_url
    print(
        f"[autoplius] WARNING: hit pagination safety bound ({PAGINATION_LIMIT}) — "
        f"stopped at {url}. Bump PAGINATION_LIMIT if this is real."
    )


def matches_filter(row: ListingRow, listing: dict) -> bool:
    """Same shape as the auto24 filter: model substring (case-insensitive) AND
    engine cc as substring of the model string."""
    if not row.model:
        return False
    model_lower = row.model.lower()

    needles = listing.get("model_contains")
    if needles:
        if isinstance(needles, str):
            needles = [needles]
        if not any(n.lower() in model_lower for n in needles):
            return False

    cc_in = listing.get("engine_cc_in")
    if cc_in:
        if not any(str(cc) in model_lower for cc in cc_in):
            return False

    return True


# ---------- detail page ----------

def fetch_ad(url: str) -> str:
    return _fetch(url)


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    el = soup.find("meta", attrs={"property": prop})
    return el.get("content") if el and el.get("content") else None


def _make_model_year(og_title: str | None) -> tuple[str | None, str | None, int | None]:
    # "Husqvarna FE 250cc, krosiniai 2016 m.,  | A29974145"
    if not og_title:
        return None, None, None
    text = re.sub(r"\s*\|\s*A\d+\s*$", "", og_title).strip()
    year_match = re.search(r"(\d{4})\s*m\.", text)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        text = text[: year_match.start()].rstrip(" ,")
    head = text.split(",", 1)[0].strip()  # "Husqvarna FE 250cc"
    head = re.sub(r"\s+\d+\s*cc\s*$", "", head, flags=re.IGNORECASE)  # drop trailing "250cc"
    parts = head.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1], year
    return head, None, year


def _engine_cc(og_keywords: str | None) -> int | None:
    if not og_keywords:
        return None
    match = re.search(r"Variklis\s+(\d+)\s*cm", og_keywords)
    return int(match.group(1)) if match else None


def _mileage_km(og_keywords: str | None) -> int | None:
    if not og_keywords:
        return None
    match = re.search(r"Rida\s+([\d\s]+)\s*km", og_keywords)
    return _to_int(match.group(1)) if match else None


def _price(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    el = (
        soup.select_one(".parameter-row-price")
        or soup.select_one(".announcement-price")
        or soup.select_one(".price")
    )
    if not el:
        return None, None
    text = el.get_text(" ", strip=True).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    digits = re.sub(r"[^\d.]", "", text.replace(",", "."))
    return (float(digits) if digits else None), text


def _location(soup: BeautifulSoup) -> str | None:
    el = soup.select_one("span.seller-contact-location")
    if not el:
        return None
    # First direct text-child holds the city, e.g. "Šilutė, Lietuva"
    for child in el.children:
        if not getattr(child, "name", None):
            txt = str(child).strip()
            if txt:
                return re.sub(r",\s*Lietuva\s*$", "", txt).strip()
    return None


def _description(soup: BeautifulSoup) -> str:
    el = soup.select_one("div.section.comments-container")
    if not el:
        return ""
    return el.get_text("\n", strip=True)


def _photos(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for slide_img in soup.select(
        "div.announcement-gallery-carousel__slide.js-announcement-gallery-thumbnail-carousel img"
    ):
        u = slide_img.get("src") or slide_img.get("data-src") or ""
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def parse_ad(html: str, url: str) -> Ad:
    soup = BeautifulSoup(html, "html.parser")
    og_title = _meta(soup, "og:title")
    og_keywords = _meta(soup, "og:keywords")
    make, model, year = _make_model_year(og_title)
    price_eur, price_display = _price(soup)
    return Ad(
        slug=_slug_from_href(url),
        url=url,
        make=make,
        model=model,
        year=year,
        engine_cc=_engine_cc(og_keywords),
        price_eur=price_eur,
        price_display=price_display,
        location=_location(soup),
        description=_description(soup),
        date_posted=None,
        photos=_photos(soup),
        mileage_km=_mileage_km(og_keywords),
    )
