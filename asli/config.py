"""Settings, model catalogue and prices."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ASLI_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_dotenv():
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

NEBIUS_API_KEY = os.environ.get("NEBIUS_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
NEBIUS_BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")

# Hard stops so the account never goes negative.
SPEND_CAP_USD = float(os.environ.get("SPEND_CAP_USD", "20"))
MONTHLY_CAP_USD = float(os.environ.get("MONTHLY_CAP_USD", "8"))
TAVILY_MONTHLY_CREDITS = int(os.environ.get("TAVILY_MONTHLY_CREDITS", "900"))

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# The listed prices below undercount the real Token Factory bill: on 29 Oct the ledger said
# $0.86 while the account balance dropped $1.40. Every recorded cost is multiplied by this
# factor so the ledger and the spend caps track real money.
BILLING_FACTOR = float(os.environ.get("BILLING_FACTOR", "1.65"))

# USD per million tokens (input, output), before BILLING_FACTOR.
MODELS = {
    "nano": {
        "id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "label": "Nemotron 3 Nano",
        "price": (0.06, 0.24),
    },
    "super": {
        "id": "nvidia/nemotron-3-super-120b-a12b",
        "label": "Nemotron 3 Super",
        "price": (0.30, 0.90),
    },
    "ultra": {
        "id": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "label": "Nemotron 3 Ultra",
        "price": (0.50, 2.20),
    },
}

# Default task routing. Overridden by data/routing.json, which the eval writes.
DEFAULT_ROUTING = {
    "read_listing": "nano",
    "market_prices": "nano",
    "community": "nano",
    "verdict": "ultra",
}

# Stores the Indian PC community generally treats as reliable.
TRUSTED_STORES = {
    "mdcomputers.in": "MD Computers",
    "primeabgb.com": "PrimeABGB",
    "vedantcomputers.com": "Vedant Computers",
    "elitehubs.com": "EliteHubs",
    "theitdepot.com": "The IT Depot",
    "pcstudio.in": "PC Studio",
}

MARKETPLACES = {
    "flipkart.com": "Flipkart",
    "amazon.in": "Amazon.in",
}

COMMUNITY_DOMAINS = ["reddit.com", "techenclave.com", "quora.com", "mouthshut.com"]
