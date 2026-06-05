from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

import cloudscraper
from bs4 import BeautifulSoup

logger = logging.getLogger("onering.watches")

_ALLOWED_HOST = "swisstimehouse.com"


def _is_swisstimehouse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == _ALLOWED_HOST or host.endswith("." + _ALLOWED_HOST)


def _extract_product_offer(html: str) -> tuple[dict, dict] | tuple[None, None]:
    """Return (product, offers) for the first schema.org Product with a usable price."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            obj_type = obj.get("@type")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            if "Product" not in types:
                continue
            if not obj.get("name"):
                continue
            offers = obj.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price")
            if price is None or price == "":
                continue
            return obj, offers
    return None, None


def fetch_swisstimehouse(url: str) -> dict | None:
    """Fetch a swisstimehouse.com product page; return {name, brand, reference, price} or None."""
    if not _is_swisstimehouse(url):
        logger.warning("Rejecting non-swisstimehouse URL: %s", url)
        return None

    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        html = response.text
    except Exception as exc:
        logger.warning("Failed to fetch swisstimehouse URL %s: %s", url, exc)
        return None

    product, offers = _extract_product_offer(html)
    if product is None:
        logger.warning("No Product JSON-LD with a price found at %s", url)
        return None

    try:
        price = float(offers["price"])
    except (ValueError, TypeError):
        logger.warning("Invalid price value at %s: %r", url, offers.get("price"))
        return None

    brand = product.get("brand") or {}
    brand_name = brand.get("name") if isinstance(brand, dict) else brand

    return {
        "name": product.get("name"),
        "brand": brand_name,
        "reference": product.get("sku") or product.get("mpn"),
        "price": price,
    }
