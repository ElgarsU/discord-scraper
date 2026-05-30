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
]


def webhook_url(listing_config: dict) -> str:
    return os.environ[listing_config["webhook_env"]]


# Top-level errors (e.g. listing fetch failure before we know which channel
# the failing item belongs to) go here. Falls back to the first listing's
# webhook so misconfiguration of an extra env var isn't fatal.
ERROR_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_ERRORS", os.environ[LISTINGS[0]["webhook_env"]]
)
