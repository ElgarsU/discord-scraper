"""auto24.ee scraper.

Notes:
- The site is fronted by Cloudflare bot management. Plain httpx with browser-
  like headers passes from residential IPs but gets a 403 challenge from
  datacenter IPs. We use curl_cffi with `impersonate="chrome"` which spoofs the
  Chrome TLS fingerprint at the network layer — that's what gets us past the
  Cloudflare check.
- The URL filter only narrows by brand (`b=`); FE 250/350 etc. is filtered
  client-side via the model name on the listing card.
- Ad detail pages do NOT expose a posted-at date. Bump detection collapses to
  price-change detection (Ad.hash falls back to slug when date_posted is None).
"""

import re
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.sources import Ad, ListingRow, http_get_impersonate

PAGINATION_LIMIT = 20  # safety bound — current largest brand fits in 2 pages at af=100


def _fetch(url: str) -> str:
    return http_get_impersonate(url)


# ---------- listing page ----------

def _slug_from_href(href: str) -> str:
    return Path(urlparse(href).path).stem


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _extract_card(card, base_url: str) -> ListingRow | None:
    link = card.select_one("a.main, a.row-link")
    if not link or not link.get("href"):
        return None
    href = link["href"]
    if "/soidukid/" not in href:
        return None
    url = urljoin(base_url, href.split("#", 1)[0])
    slug = _slug_from_href(href)

    # Build a free-form "model" string the filter can substring-match against.
    # Combine the model + trim cells so e.g. "FE 350 Rockstars" or "FE350" both
    # round-trip when sellers type with/without the space.
    parts: list[str] = []
    model_el = card.select_one(".title .model")
    if model_el and model_el.get_text(strip=True):
        parts.append(model_el.get_text(strip=True))
    trim_el = card.select_one(".title .model-trim")
    if trim_el and trim_el.get_text(strip=True):
        parts.append(trim_el.get_text(strip=True))
    model = " ".join(parts) if parts else None

    year = _to_int(card.select_one(".extra .year").get_text(strip=True)) \
        if card.select_one(".extra .year") else None
    price_text = card.select_one(".title .price").get_text(strip=True) \
        if card.select_one(".title .price") else None

    return ListingRow(
        slug=slug,
        url=url,
        model=model,
        year=year,
        engine_cc=None,  # not on listing card; verified post-fetch
        price_text=price_text,
        region=None,     # location only on detail page
    )


def _parse_rows(html: str, base_url: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="usedVehiclesSearchResult-flex")
    if not container:
        return []
    out: list[ListingRow] = []
    for card in container.find_all("div", class_="result-row"):
        row = _extract_card(card, base_url)
        if row:
            out.append(row)
    return out


def _next_page_url(html: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("div.paginator__next a[rel='next'][href]")
    return urljoin(current_url, link["href"]) if link else None


def iter_all_rows(base_url: str) -> Iterator[ListingRow]:
    url = base_url
    for _ in range(PAGINATION_LIMIT):
        html = _fetch(url)
        yield from _parse_rows(html, url)
        next_url = _next_page_url(html, url)
        if not next_url:
            return
        url = next_url
    print(
        f"[auto24] WARNING: hit pagination safety bound ({PAGINATION_LIMIT}) — "
        f"stopped at {url}. Bump PAGINATION_LIMIT if this is real."
    )


def matches_filter(row: ListingRow, listing: dict) -> bool:
    """Match rule for auto24 (no structured engine_cc on listing card):

      - model_contains: list of substrings (any-match), case-insensitive
      - engine_cc_in:   list of ints; matches if str(cc) appears anywhere in model

    Both groups must match (AND across groups, OR within each group). Example:
    `model_contains=["fe"]` + `engine_cc_in=[250, 350]` accepts "FE 250", "fe350",
    "FE 350 Rockstars" — but rejects "TC 65" or "FE 501".
    """
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


def _spec(soup: BeautifulSoup, row_class: str) -> str | None:
    tr = soup.select_one(f"table.main-data tr.{row_class}")
    if not tr:
        return None
    val = tr.select_one("td.field span.value")
    return val.get_text(strip=True) if val else None


def _year_from_first_reg(value: str | None) -> int | None:
    # "02/2023" → 2023
    if not value:
        return None
    match = re.search(r"(\d{4})", value)
    return int(match.group(1)) if match else None


def _engine_cc(value: str | None) -> int | None:
    # "350cm³" → 350; "250cm³ 11kW" → 250 (don't fold the kW digits in)
    if not value:
        return None
    match = re.search(r"(\d+)\s*cm", value)
    return int(match.group(1)) if match else None


def _price_eur(value: str | None) -> tuple[float | None, str | None]:
    # "6800 EUR" → (6800.0, "6800 EUR")
    if not value:
        return None, None
    cleaned = value.replace("\xa0", " ").strip()
    digits = re.sub(r"[^\d.]", "", cleaned.replace(",", "."))
    return (float(digits) if digits else None), cleaned


def _location(soup: BeautifulSoup) -> str | None:
    el = soup.select_one("div.-location b")
    return el.get_text(strip=True) if el else None


def _description(soup: BeautifulSoup) -> str:
    # NB: html.parser parses self-closing <br/> as an open tag, so any
    # text that follows becomes a child of the <br>. Don't rewrite <br>s —
    # get_text with a separator handles whitespace cleanly enough.
    el = soup.select_one("div.section.other-info div.-user_other")
    if not el:
        return ""
    text = el.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _photos(soup: BeautifulSoup) -> list[str]:
    # The gallery wraps each thumb in <a href="https://...img-bcg.eu/h30/.../id.jpg">
    urls: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=re.compile(r"img-bcg")):
        href = a["href"]
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


def _make_model(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    # auto24 sometimes appends the engine power to the title, e.g. "KTM 250 EXC-F 11kW".
    # Strip the trailing power so the model field stays clean.
    h1 = soup.find("h1")
    if not h1:
        return None, None
    text = re.sub(r"\s+\d+\s*kW\s*$", "", h1.get_text(" ", strip=True), flags=re.IGNORECASE)
    parts = text.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return text, None


def parse_ad(html: str, url: str) -> Ad:
    soup = BeautifulSoup(html, "html.parser")
    make, model = _make_model(soup)
    price_eur, price_display = _price_eur(_spec(soup, "field-hind"))
    return Ad(
        slug=_slug_from_href(url),
        url=url,
        make=make,
        model=model,
        year=_year_from_first_reg(_spec(soup, "field-month_and_year")),
        engine_cc=_engine_cc(_spec(soup, "field-mootorvoimsus")),
        price_eur=price_eur,
        price_display=price_display,
        location=_location(soup),
        description=_description(soup),
        date_posted=None,  # not exposed on the page
        photos=_photos(soup),
        mileage_km=_to_int(_spec(soup, "field-labisoit")),
    )
