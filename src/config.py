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
        "name": "ss.com — Husqvarna TE 300 (2-stroke)",
        "base_url": "https://www.ss.com/lv/transport/moto-transport/motorcycles/husqvarna/",
        # "fe"/"te" both kept because sellers mislabel the model; the 300-only
        # cc filter is what restricts this to the 2-stroke (TE 300).
        "model_contains": ["fe", "te"],
        "engine_cc_in": [300],
        "webhook_env": "DISCORD_WEBHOOK_HUSQVARNA_FE",
    },
    {
        "source": "ss",
        "key": "ss-ktm-exc",
        "name": "ss.com — KTM EXC 300 (2-stroke)",
        "base_url": "https://www.ss.com/lv/transport/moto-transport/motorcycles/ktm/",
        # "exc" already substring-matches "exc-f"/"excf"; listed explicitly to
        # document that mislabeled 4-stroke entries are intentionally caught.
        "model_contains": ["exc", "exc-f", "excf"],
        "engine_cc_in": [300],
        "webhook_env": "DISCORD_WEBHOOK_KTM_EXC",
    },
    {
        "source": "ss",
        "key": "ss-sherco-beta-gasgas",
        "name": "ss.com — Sherco / Beta / GasGas 2-stroke (250–300cc, 2020+)",
        # This source drives the ss.com search form across ALL makes (no per-make
        # URL). The server does the coarse cut — year >= 2020 and 250–300cc — so
        # the client-side needle match works on a small, mostly-relevant set.
        "search": {
            "base_url": "https://www.ss.com/lv/transport/moto-transport/motorcycles/",
            "year_min": 2020,
            "cc_min": 250,
            "cc_max": 300,
        },
        # Brand + model-code fragments. Short ones (se/rr/ec/gas) are only safe
        # because the 250–300cc server filter already removed the superbikes,
        # motocross, and mowers they'd otherwise match. Matched against make+model.
        "model_contains": ["se", "rr", "sherco", "beta", "ec", "gas", "gasgas", "gas gas"],
        # Kill the residual look-alikes the short fragments still catch:
        # "Hecht" (garden brand, via "ec"), "Berreta"/"Beretta" pit-bikes (via "rr").
        "model_excludes": ["hecht", "berreta", "beretta"],
        # Redundant with the server filter, but a cheap guard if the form ever
        # returns an out-of-range row.
        "year_min": 2020,
        "webhook_env": "DISCORD_WEBHOOK_SHERCO_BETA",
    },
    {
        "source": "ss",
        "key": "ss-125cc",
        "name": "ss.com — 125cc (2018+, €2000–4000, negative-filtered)",
        # Search across ALL makes: 125cc only, year >= 2018, €2000–4000. No
        # positive (model_contains) filter — every result that survives the
        # negative filter below is reported. The exclude list is curated by hand
        # and grows over time to weed out unwanted models.
        "search": {
            "base_url": "https://www.ss.com/lv/transport/moto-transport/motorcycles/",
            "year_min": 2018,
            "cc_min": 125,
            "cc_max": 125,
            "price_min": 2000,
            "price_max": 4000,
        },
        # Negative filter — matched against the Modelis column ONLY (see
        # matches_filter). Drop an ad if its model contains any of these.
        "model_excludes": [
            "svartpilen", "duke", "ked", "dukka", "xsr", "mt", "niu",
            "fantic", "zontes", "macbor", "dukkalon", "yzf", "hps", "blade",
            "mondial", "duo", "renegade", "scrambler", "qj", "mutt", "aventura",
            "tuono", "zt", "tourer", "dune", "mash", "black", "seventy", "xride",
            "junak", "glr", "cbf", "superlight",
            "cf125", "cb125", "flat track 125", "cf125nk", "gt-125", "keeway",
            "nr125x", "n125v",
        ],
        # Make-column negative filter — drop these makes entirely.
        "make_excludes": ["benelli", "cf moto"],
        "year_min": 2018,
        "webhook_env": "DISCORD_WEBHOOK_125CC",
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
