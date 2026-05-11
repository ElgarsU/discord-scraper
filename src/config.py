import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "scraper.db"
DB_PATH = os.environ.get("DB_PATH", str(_DEFAULT_DB))

IMAGES_DIR = os.environ.get("IMAGES_DIR", str(Path(DB_PATH).parent / "images"))

LISTINGS = [
    {
        "source": "ss",
        "key": "ss-husqvarna-fe",
        "name": "ss.com — Husqvarna FE 250/350",
        "base_url": "https://www.ss.com/lv/transport/moto-transport/motorcycles/husqvarna/",
        "model_contains": "fe",
        "engine_cc_in": [250, 350],
        "webhook_env": "DISCORD_WEBHOOK_HUSQVARNA_FE",
    },
    {
        "source": "auto24",
        "key": "auto24-husqvarna-fe",
        "name": "auto24.ee — Husqvarna FE 250/350",
        "base_url": "https://www.auto24.ee/kasutatud/nimekiri.php?bn=2&a=100&b=345&af=100",
        "model_contains": "fe",
        "engine_cc_in": [250, 350],
        "webhook_env": "DISCORD_WEBHOOK_AUTO24_HUSQVARNA_FE",
    },
    {
        "source": "mototehnika",
        "key": "mototehnika-husqvarna-fe",
        "name": "mototehnika.ee — Husqvarna FE 250/350",
        "base_url": "https://www.mototehnika.ee/kasutatud/nimekiri.php?bn=2&a=109&b=345&w1=250&w2=350&af=100",
        "model_contains": "fe",
        "engine_cc_in": [250, 350],
        "webhook_env": "DISCORD_WEBHOOK_MOTOTEHNIKA_HUSQVARNA_FE",
    },
    {
        "source": "autoplius",
        "key": "autoplius-husqvarna-fe",
        "name": "autoplius.lt — Husqvarna FE 250/350",
        "base_url": "https://autoplius.lt/skelbimai/motociklai-moto-apranga/motociklai?make_id=1584&engine_capacity_from=250&engine_capacity_to=450",
        "model_contains": "fe",
        "engine_cc_in": [250, 350],
        "webhook_env": "DISCORD_WEBHOOK_AUTOPLIUS_HUSQVARNA_FE",
    },
]


def webhook_url(listing_config: dict) -> str:
    return os.environ[listing_config["webhook_env"]]


# Top-level errors (e.g. listing fetch failure before we know which channel
# the failing item belongs to) go here. Falls back to the first listing's
# webhook so misconfiguration of an extra env var isn't fatal.
ERROR_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_ERRORS", os.environ[LISTINGS[0]["webhook_env"]]
)
