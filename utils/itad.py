import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

_BASE_URL = "https://api.isthereanydeal.com"

logger = logging.getLogger("onering.itad")

_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def _api_key() -> str:
    load_dotenv()
    return os.environ["ITAD_API_KEY"]


@_retry
def search_game(title: str) -> Optional[dict]:
    """Search ITAD for a game by title. Returns the first match or None."""
    logger.info("Searching ITAD for: %s", title)
    response = requests.get(
        f"{_BASE_URL}/games/search/v1",
        params={"title": title, "key": _api_key()},
        timeout=30,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        logger.info("No results found for: %s", title)
        return None
    logger.info("Found: %s (id=%s)", results[0].get("title"), results[0].get("id"))
    return results[0]


@_retry
def get_best_price(itad_id: str) -> Optional[dict]:
    """Best current price across stores for an ITAD id. Keys: price, regular_price, store, cut."""
    logger.info("Fetching prices for ITAD id: %s", itad_id)
    response = requests.post(
        f"{_BASE_URL}/games/prices/v3",
        params={"key": _api_key(), "country": "IN"},
        json=[itad_id],
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data or not data[0].get("deals"):
        logger.info("No deals found for: %s", itad_id)
        return None
    deals = data[0]["deals"]
    best = min(deals, key=lambda d: d["price"]["amount"])
    return {
        "price": best["price"]["amount"],
        "regular_price": best["regular"]["amount"],
        "store": best["shop"]["name"],
        "cut": best["cut"],
    }


@_retry
def get_historical_low(itad_id: str) -> Optional[float]:
    """All-time historical low price (INR) for a game from ITAD, or None."""
    logger.info("Fetching historical low for ITAD id: %s", itad_id)
    response = requests.post(
        f"{_BASE_URL}/games/historylow/v1",
        params={"key": _api_key(), "country": "IN"},
        json=[itad_id],
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data or not data[0].get("low"):
        logger.info("No historical low found for: %s", itad_id)
        return None
    return float(data[0]["low"]["price"]["amount"])


@_retry
def get_all_prices(itad_id: str) -> list[dict]:
    """All current store prices for an ITAD id, sorted ascending by price."""
    logger.info("Fetching all prices for ITAD id: %s", itad_id)
    response = requests.post(
        f"{_BASE_URL}/games/prices/v3",
        params={"key": _api_key(), "country": "IN"},
        json=[itad_id],
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data or not data[0].get("deals"):
        return []
    parsed = [
        {
            "price": d["price"]["amount"],
            "regular_price": d["regular"]["amount"],
            "store": d["shop"]["name"],
            "cut": d["cut"],
        }
        for d in data[0]["deals"]
    ]
    parsed.sort(key=lambda x: x["price"])
    return parsed
