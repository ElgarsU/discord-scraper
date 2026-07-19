"""ss.com scraper."""

import re
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.sources import Ad, HEADERS, ListingRow, RIGA, http_get


# ---------- listing page ----------

def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _parse_rows(html: str, base_url: str, has_make: bool = False) -> list[ListingRow]:
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
        make = model = year = engine_cc = price_text = None
        # Per-make category pages: [model, year, cc, price]. The search-result
        # page carries an extra leading make column: [make, model, year, cc, price].
        offset = 1 if has_make else 0
        if len(cells) >= offset + 4:
            if has_make:
                make = cells[0].get_text(strip=True) or None
            model = cells[offset].get_text(strip=True) or None
            year = _to_int(cells[offset + 1].get_text(strip=True))
            engine_cc = _to_int(cells[offset + 2].get_text(strip=True))
            price_text = cells[offset + 3].get_text(strip=True) or None

        region = None
        region_div = tr.find("div", class_="ads_region")
        if region_div:
            region = region_div.get_text(strip=True)

        rows.append(
            ListingRow(slug, url, model, year, engine_cc, price_text, region, make)
        )
    return rows


def _discover_max_page(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    nums = []
    for a in soup.select("a[href]"):
        match = re.search(r"/page(\d+)\.html$", a.get("href", ""))
        if match:
            nums.append(int(match.group(1)))
    return max(nums) if nums else 1


def iter_all_rows(listing: dict) -> Iterator[ListingRow]:
    """Yield every listing row for a source config. A config with a ``search``
    block drives the ss.com search form (all makes, server-side cc/year
    filtering); otherwise it paginates a per-make category ``base_url``."""
    search = listing.get("search")
    if search:
        yield from _iter_search_rows(search)
    else:
        yield from _iter_category_rows(listing["base_url"])


def _iter_category_rows(base_url: str) -> Iterator[ListingRow]:
    if not base_url.endswith("/"):
        base_url += "/"
    page_one = http_get(base_url).text
    yield from _parse_rows(page_one, base_url)
    last_page = _discover_max_page(page_one)
    for n in range(2, last_page + 1):
        html = http_get(base_url + f"page{n}.html").text
        yield from _parse_rows(html, base_url)


# The search form POSTs every field; unset ones must still be present (empty or
# "0"). Notably the make field ``opt[227][]`` is OMITTED entirely — sending it
# empty makes ss.com return zero results. cc/year get overwritten per config.
_SEARCH_DEFAULT_PARAMS = {
    "txt": "",
    "topt[24]": "",
    "topt[18][min]": "0",  # year min
    "topt[18][max]": "0",  # year max (0 = any)
    "topt[989][min]": "",  # engine cc min
    "topt[989][max]": "",  # engine cc max
    "topt[8][min]": "",  # price min
    "topt[8][max]": "",  # price max
    "sid": "",
    "search_region": "0",
    "pr": "0",
    "sort": "0",
}


def _iter_search_rows(search: dict) -> Iterator[ListingRow]:
    base = search["base_url"]
    if not base.endswith("/"):
        base += "/"
    form_url = base + "search/"
    result_url = base + "search-result/"

    params = dict(_SEARCH_DEFAULT_PARAMS)
    if search.get("year_min") is not None:
        params["topt[18][min]"] = str(search["year_min"])
    if search.get("year_max") is not None:
        params["topt[18][max]"] = str(search["year_max"])
    if search.get("cc_min") is not None:
        params["topt[989][min]"] = str(search["cc_min"])
    if search.get("cc_max") is not None:
        params["topt[989][max]"] = str(search["cc_max"])
    if search.get("price_min") is not None:
        params["topt[8][min]"] = str(search["price_min"])
    if search.get("price_max") is not None:
        params["topt[8][max]"] = str(search["price_max"])

    # ss.com stores the search criteria in a server-side PHP session and
    # 302-redirects to the result page, so we need a cookie jar: GET the form to
    # seed the session, POST the criteria, then paginate within the same client.
    with httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        client.get(form_url)
        first = client.post(result_url, data=params, headers={"Referer": form_url})
        first.raise_for_status()
        yield from _parse_rows(first.text, result_url, has_make=True)
        last_page = _discover_max_page(first.text)
        for n in range(2, last_page + 1):
            page = client.get(
                result_url + f"page{n}.html", headers={"Referer": result_url}
            )
            page.raise_for_status()
            yield from _parse_rows(page.text, result_url, has_make=True)


def matches_filter(row: ListingRow, listing: dict) -> bool:
    # Match against make + model so needles/excludes can hit either. On category
    # pages make is None, so this collapses to the model text (unchanged behavior).
    haystack = " ".join(p for p in (row.make, row.model) if p).lower()

    needles = listing.get("model_contains")
    if needles:
        if isinstance(needles, str):
            needles = [needles]
        if not haystack:
            return False
        if not any(n.lower() in haystack for n in needles):
            return False

    # Excludes match the model column ONLY (not make) — negative filtering
    # targets the "Modelis" field, and a short fragment like "na" must not knock
    # out an entire make via e.g. "Husqvar-na".
    excludes = listing.get("model_excludes")
    if excludes:
        if isinstance(excludes, str):
            excludes = [excludes]
        model_lower = (row.model or "").lower()
        if any(x.lower() in model_lower for x in excludes):
            return False

    # Make-column negative filter — drop whole makes regardless of model.
    make_excludes = listing.get("make_excludes")
    if make_excludes:
        if isinstance(make_excludes, str):
            make_excludes = [make_excludes]
        make_lower = (row.make or "").lower()
        if any(x.lower() in make_lower for x in make_excludes):
            return False

    cc_in = listing.get("engine_cc_in")
    if cc_in and row.engine_cc not in cc_in:
        return False

    year_min = listing.get("year_min")
    if year_min is not None and row.year is not None and row.year < year_min:
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
