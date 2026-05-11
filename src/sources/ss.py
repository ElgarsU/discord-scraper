"""ss.com scraper."""

import re
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.sources import Ad, ListingRow, RIGA, http_get


# ---------- listing page ----------

def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _parse_rows(html: str, base_url: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ListingRow] = []
    for tr in soup.find_all("tr"):
        tr_id = tr.get("id", "")
        if not re.fullmatch(r"tr_\d+", tr_id):
            continue
        link = tr.find("a", href=re.compile(r"/msg/.+\.html"))
        if not link:
            continue
        href = link["href"]
        url = urljoin(base_url, href)
        slug = Path(urlparse(href).path).stem

        cells = tr.find_all("td", class_="msga2-o")
        model = year = engine_cc = price_text = None
        if len(cells) >= 4:
            model = cells[0].get_text(strip=True) or None
            year = _to_int(cells[1].get_text(strip=True))
            engine_cc = _to_int(cells[2].get_text(strip=True))
            price_text = cells[3].get_text(strip=True) or None

        region = None
        region_div = tr.find("div", class_="ads_region")
        if region_div:
            region = region_div.get_text(strip=True)

        rows.append(ListingRow(slug, url, model, year, engine_cc, price_text, region))
    return rows


def _discover_max_page(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    nums = []
    for a in soup.select("a[href]"):
        match = re.search(r"/page(\d+)\.html$", a.get("href", ""))
        if match:
            nums.append(int(match.group(1)))
    return max(nums) if nums else 1


def iter_all_rows(base_url: str) -> Iterator[ListingRow]:
    if not base_url.endswith("/"):
        base_url += "/"
    page_one = http_get(base_url).text
    yield from _parse_rows(page_one, base_url)
    last_page = _discover_max_page(page_one)
    for n in range(2, last_page + 1):
        html = http_get(base_url + f"page{n}.html").text
        yield from _parse_rows(html, base_url)


def matches_filter(row: ListingRow, listing: dict) -> bool:
    needles = listing.get("model_contains")
    if needles:
        if isinstance(needles, str):
            needles = [needles]
        if not row.model:
            return False
        model_lower = row.model.lower()
        if not any(n.lower() in model_lower for n in needles):
            return False
    cc_in = listing.get("engine_cc_in")
    if cc_in and row.engine_cc not in cc_in:
        return False
    return True


# ---------- detail page ----------

def fetch_ad(url: str) -> str:
    return http_get(url).text


def _by_id(soup: BeautifulSoup, element_id: str) -> str | None:
    el = soup.find(id=element_id)
    return el.get_text(strip=True) if el else None


def _description(soup: BeautifulSoup) -> str:
    msg_div = soup.find("div", id="msg_div_msg")
    if not msg_div:
        return ""
    inner = msg_div.decode_contents()
    cut = inner.find("<table")
    if cut > 0:
        inner = inner[:cut]
    fragment = BeautifulSoup(inner, "html.parser")
    for br in fragment.find_all("br"):
        br.replace_with("\n")
    text = fragment.get_text()
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text.strip()


def _photos(soup: BeautifulSoup) -> list[str]:
    return [
        a["href"]
        for a in soup.select("div.pic_dv_thumbnail > a")
        if a.get("href")
    ]


def _location(soup: BeautifulSoup) -> str | None:
    for label in soup.find_all("td", class_="ads_contacts_name"):
        if "Vieta" in label.get_text():
            sibling = label.find_next_sibling("td")
            if sibling:
                return sibling.get_text(strip=True)
    return None


def _price_eur(html: str) -> float | None:
    match = re.search(r"var MSG_PRICE\s*=\s*([0-9.]+)", html)
    return float(match.group(1)) if match else None


def _date_posted(html: str) -> datetime | None:
    match = re.search(r"Datums:\s*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", html)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d.%m.%Y %H:%M").replace(tzinfo=RIGA)


def _slug_from_url(url: str) -> str:
    return Path(urlparse(url).path).stem


def parse_ad(html: str, url: str) -> Ad:
    soup = BeautifulSoup(html, "html.parser")
    return Ad(
        slug=_slug_from_url(url),
        url=url,
        make=_by_id(soup, "tdo_227"),
        model=_by_id(soup, "tdo_24"),
        year=_to_int(_by_id(soup, "tdo_18")),
        engine_cc=_to_int(_by_id(soup, "tdo_989")),
        price_eur=_price_eur(html),
        price_display=_by_id(soup, "tdo_8"),
        location=_location(soup),
        description=_description(soup),
        date_posted=_date_posted(html),
        photos=_photos(soup),
    )
