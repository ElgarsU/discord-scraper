import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from src.sources import Ad

COLOR_NEW = 0x4CAF50
COLOR_BUMPED = 0xFFC107
COLOR_GONE = 0x9E9E9E
COLOR_ERROR = 0xE53935
DESCRIPTION_LIMIT = 4000
ERROR_DESCRIPTION_LIMIT = 1900
GALLERY_LIMIT = 10


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _row_get(row, key: str):
    """sqlite3.Row raises IndexError on missing keys — fall back to None so
    code can read columns that may not exist in older DB schemas."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _build_embeds(ad: Ad, kind: str) -> list[dict]:
    is_bumped = kind == "bumped"
    emoji = "🔁" if is_bumped else "🆕"
    color = COLOR_BUMPED if is_bumped else COLOR_NEW

    title_parts = [emoji, f"{ad.make or ''} {ad.model or ''}".strip()]
    if ad.year:
        title_parts[-1] += f", {ad.year}"
    if ad.price_display:
        title_parts.append(f"— {ad.price_display}")
    title = " ".join(p for p in title_parts if p)

    fields = []
    if ad.engine_cc:
        fields.append({"name": "Engine", "value": f"{ad.engine_cc} cm³", "inline": True})
    if ad.mileage_km is not None:
        fields.append({"name": "Mileage", "value": f"{ad.mileage_km:,} km".replace(",", " "), "inline": True})
    if ad.location:
        fields.append({"name": "Location", "value": ad.location, "inline": True})
    if ad.date_posted:
        fields.append({"name": "Date posted", "value": ad.date_posted_display, "inline": True})

    main = {
        "title": title,
        "url": ad.url,
        "color": color,
        "description": _truncate(ad.description, DESCRIPTION_LIMIT) if ad.description else None,
        "fields": fields,
    }
    main = {k: v for k, v in main.items() if v not in (None, [])}

    photos = ad.photos[:GALLERY_LIMIT]
    embeds: list[dict] = []
    if photos:
        main["image"] = {"url": photos[0]}
        embeds.append(main)
        for photo in photos[1:]:
            embeds.append({"url": ad.url, "image": {"url": photo}})
    else:
        embeds.append(main)
    return embeds


def send_ad(webhook_url: str, ad: Ad, kind: str) -> str:
    """Posts the ad embeds and returns the Discord message ID, which we store so
    later 'gone' notifications can reply to this exact message."""
    payload = {"embeds": _build_embeds(ad, kind)}
    response = httpx.post(_with_wait(webhook_url), json=payload, timeout=15)
    response.raise_for_status()
    return response.json()["id"]


def _with_wait(webhook_url: str) -> str:
    sep = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{sep}wait=true"


def send_error(webhook_url: str, exc: BaseException, context: str = "") -> None:
    body = f"{type(exc).__name__}: {exc}"
    if context:
        body = f"{context}\n\n{body}"
    embed = {
        "title": "⚠️ Scrape failed",
        "description": _truncate(body, ERROR_DESCRIPTION_LIMIT),
        "color": COLOR_ERROR,
    }
    response = httpx.post(webhook_url, json={"embeds": [embed]}, timeout=15)
    response.raise_for_status()


_webhook_info_cache: dict[str, dict] = {}


def _webhook_info(webhook_url: str) -> dict:
    if webhook_url not in _webhook_info_cache:
        response = httpx.get(webhook_url, timeout=10)
        response.raise_for_status()
        _webhook_info_cache[webhook_url] = response.json()
    return _webhook_info_cache[webhook_url]


def _jump_url(webhook_url: str, message_id: str) -> str:
    info = _webhook_info(webhook_url)
    return f"https://discord.com/channels/{info['guild_id']}/{info['channel_id']}/{message_id}"


def _ad_label(ad_row) -> str:
    parts = [ad_row["make"] or "", ad_row["model"] or ""]
    label = " ".join(p for p in parts if p).strip() or ad_row["ad_slug"]
    if ad_row["year"]:
        label += f", {ad_row['year']}"
    if ad_row["price_display"]:
        label += f" — {ad_row['price_display']}"
    return label


def mark_ad_gone(webhook_url: str, ad_row) -> str:
    """Edit the original notification in place (grey + GONE prefix + strikethrough
    + 'Disappeared' timestamp field) and post a short pointer message linking
    back to the edited message. Returns a status string describing what happened."""
    message_id = None
    try:
        message_id = ad_row["discord_message_id"]
    except (IndexError, KeyError):
        message_id = None

    embeds = _build_gone_embeds(ad_row)

    if not message_id:
        response = httpx.post(webhook_url, json={"embeds": embeds}, timeout=15)
        response.raise_for_status()
        return "posted-new (no original message id)"

    edit_url = f"{webhook_url}/messages/{message_id}"
    response = httpx.patch(edit_url, json={"embeds": embeds}, timeout=15)
    if response.status_code == 404:
        response = httpx.post(webhook_url, json={"embeds": embeds}, timeout=15)
        response.raise_for_status()
        return "posted-new (original deleted)"
    response.raise_for_status()

    pointer = f"🚫 Gone: **{_ad_label(ad_row)}**\n{_jump_url(webhook_url, message_id)}"
    pointer_response = httpx.post(webhook_url, json={"content": pointer}, timeout=15)
    pointer_response.raise_for_status()
    return "edited + pointer"


def _build_gone_embeds(ad_row) -> list[dict]:
    label_parts = [ad_row["make"] or "", ad_row["model"] or ""]
    label = " ".join(p for p in label_parts if p).strip() or ad_row["ad_slug"]
    if ad_row["year"]:
        label += f", {ad_row['year']}"
    if ad_row["price_display"]:
        label += f" — {ad_row['price_display']}"
    title = f"🚫 GONE — ~~{label}~~"

    fields = []
    if ad_row["engine_cc"]:
        fields.append({"name": "Engine", "value": f"{ad_row['engine_cc']} cm³", "inline": True})
    if _row_get(ad_row, "mileage_km") is not None:
        km = ad_row["mileage_km"]
        fields.append({"name": "Mileage", "value": f"{km:,} km".replace(",", " "), "inline": True})
    if ad_row["location"]:
        fields.append({"name": "Location", "value": ad_row["location"], "inline": True})
    if ad_row["date_posted"]:
        fields.append({"name": "Date posted", "value": ad_row["date_posted"][:16].replace("T", " "), "inline": True})
    fields.append({
        "name": "Disappeared",
        "value": datetime.now(ZoneInfo("Europe/Riga")).strftime("%Y-%m-%d %H:%M"),
        "inline": True,
    })

    main = {
        "title": title,
        "url": ad_row["ad_url"],
        "color": COLOR_GONE,
        "fields": fields,
    }
    description = ad_row["description"]
    if description:
        main["description"] = _truncate(description, DESCRIPTION_LIMIT)

    photos: list[str] = []
    if ad_row["photo_urls"]:
        try:
            photos = json.loads(ad_row["photo_urls"]) or []
        except json.JSONDecodeError:
            photos = []
    photos = photos[:GALLERY_LIMIT]

    embeds: list[dict] = []
    if photos:
        main["image"] = {"url": photos[0]}
        embeds.append(main)
        for photo in photos[1:]:
            embeds.append({"url": ad_row["ad_url"], "image": {"url": photo}})
    else:
        embeds.append(main)
    return embeds
