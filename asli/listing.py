"""Step 1: read a listing URL into structured fields."""
import hashlib
import json
import re
from urllib.parse import urlparse

import requests

from . import llm, tavily
from .config import MARKETPLACES, TRUSTED_STORES

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

FIELDS = """{
  "is_product_page": bool,
  "title": str,
  "brand": str|null,
  "gpu": str|null,            // normalised chip + memory, e.g. "RTX 3060 12GB"
  "price_inr": int|null,      // price the buyer pays now
  "mrp_inr": int|null,        // struck-through MRP, if shown
  "in_stock": bool|null,      // can it be bought right now?
  "availability_text": str|null, // exact wording, e.g. "Notify Me", "Currently unavailable"
  "seller": str|null,         // "Sold by" name
  "fulfilled_by_platform": bool|null,
  "returnable": bool|null,
  "warranty_text": str|null,
  "rating": float|null,
  "rating_count": int|null,
  "other_offers": [{"seller": str, "price_inr": int}]
}"""

SYSTEM = ("You read Indian e-commerce product pages and return the listing facts as JSON. "
          "Use only what the page text says; use null when a field is not stated. "
          "Prices are integers in rupees without commas.")


def canonical(url):
    """Drop tracking params and Flipkart's language prefix so one listing has one URL."""
    url = url.strip()
    if "flipkart.com" in url:
        url = url.split("?")[0].replace("flipkart.com/hi/", "flipkart.com/")
    return url


def store_of(url):
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, name in {**MARKETPLACES, **TRUSTED_STORES}.items():
        if host.endswith(domain):
            return {"domain": domain, "name": name,
                    "kind": "marketplace" if domain in MARKETPLACES else "trusted"}
    return {"domain": host, "name": host, "kind": "unknown"}


GPU_RE = re.compile(
    r"\b(RTX|GTX|RX|ARC)\s?-?\s?([A-Z]?\d{3,4})\s?(TI SUPER|TI|SUPER|XTX|XT|GRE)?\b", re.I)
MEM_RE = re.compile(r"\b(\d{1,2})\s?GB\b", re.I)


def normalise_gpu(text):
    if not text:
        return None
    m = GPU_RE.search(text)
    if not m:
        return None
    chip = f"{m.group(1).upper()} {m.group(2).upper()}"
    if m.group(3):
        chip += " " + m.group(3).title().replace("Xtx", "XTX").replace("Xt", "XT").replace("Gre", "GRE")
    mem = MEM_RE.search(text)
    return f"{chip} {mem.group(1)}GB" if mem else chip


def _flag(html, name):
    m = re.search(rf'"{name}":(true|false)', html)
    return None if not m else m.group(1) == "true"


def _str(html, name):
    m = re.search(rf'"{name}":"([^"]+)"', html)
    return m.group(1) if m else None


def parse_flipkart(html):
    """Pull listing facts from the JSON Flipkart embeds in its product page."""
    out = {"is_product_page": True, "other_offers": []}
    ld = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S)
    ld_price = None
    if ld:
        try:
            block = json.loads(ld.group(1))
            block = block[0] if isinstance(block, list) else block
            out["title"] = block.get("name")
            m = re.search(r"Rs\.\s?([\d.]+)", block.get("description", ""))
            ld_price = int(float(m.group(1))) if m else None
        except (json.JSONDecodeError, IndexError, AttributeError):
            pass
    button = _str(html, "productActionButtonType") or ""
    m = re.search(r'"productActionButtonType":"[^"]+","text":"([^"]+)"', html)
    m_price = re.search(r'"price":(\d+),"productActionButtonType"', html) or \
        re.search(r'label_random_to_get_price_in_child_header":\{"value":\{"text":(\d+)', html)
    out["price_inr"] = int(m_price.group(1)) if m_price else None
    m_disc = re.search(r'Discount on MRP"\}\},"label_11":\{"value":\{"text":"-₹([\d,]+)"', html)
    if out["price_inr"] and m_disc:
        out["mrp_inr"] = out["price_inr"] + int(m_disc.group(1).replace(",", ""))
    elif ld_price and out["price_inr"] and ld_price > out["price_inr"]:
        out["mrp_inr"] = ld_price
    else:
        out["mrp_inr"] = None
    status = _str(html, "availabilityStatus")
    out["availability_text"] = (m.group(1) if m else None) or status
    out["in_stock"] = None if status is None else status == "IN_STOCK" and "NOTIFY" not in button
    out["seller"] = None
    out["seller_id"] = _str(html, "sellerId")
    out["fulfilled_by_platform"] = _flag(html, "fbf")
    out["platform_assured"] = _flag(html, "fa")
    out["gst_invoice"] = _flag(html, "gstbillingAvailable")
    out["brand"] = _str(html, "bd")
    m = re.search(r'"rating":([\d.]+),"ratingsCount":(\d+)', html)
    out["rating"], out["rating_count"] = (float(m.group(1)), int(m.group(2))) if m else (None, None)
    m = re.search(r"(\d+)\s?Days?\s+(?:Replacement|Return)", html, re.I)
    out["returnable"] = True if m else None
    out["return_policy"] = m.group(0) if m else None
    out["warranty_text"] = None
    out["raw_status"] = {"availabilityStatus": status, "button": button,
                         "nonBuyableReason": _str(html, "nonBuyablilityReason")}
    return out


def fetch_flipkart(url):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en"}, timeout=30)
    if r.status_code != 200 or "productActionButtonType" not in r.text:
        return None, None
    return parse_flipkart(r.text), hashlib.sha1(r.content).hexdigest()


def _trim(text, limit=12000):
    """Keep the head of the page plus any later lines that carry buying facts."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    keys = re.compile(r"₹|rs\.?\s?\d|sold by|seller|ships from|stock|notify|unavailable|"
                      r"return|warranty|mrp|rating", re.I)
    extra = [l for l in text[limit // 2:].splitlines() if keys.search(l) and len(l) < 400]
    return head + "\n...\n" + "\n".join(extra)[: limit // 2]


def extract_with_model(text, url, store):
    user = (f"Store: {store['name']}\nURL: {url}\n\nReturn JSON with exactly these fields:\n"
            f"{FIELDS}\n\nPAGE TEXT:\n{_trim(text)}")
    return llm.chat_json("read_listing", SYSTEM, user, max_tokens=1500)


def _walk_products(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk_products(n)
    elif isinstance(node, dict):
        if node.get("@type") in ("Product", ["Product"]):
            yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk_products(v)


def structured_offer(url):
    """Price and stock from the page's schema.org Product data, or None."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', r.text, re.S):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for prod in _walk_products(data):
            offers = prod.get("offers")
            for o in offers if isinstance(offers, list) else [offers]:
                if not isinstance(o, dict):
                    continue
                price = o.get("price") or o.get("lowPrice")
                avail = str(o.get("availability") or "")
                return {"name": prod.get("name"),
                        "price_inr": int(float(price)) if price else None,
                        "in_stock": ("InStock" in avail) if avail else None,
                        "availability": avail.rsplit("/", 1)[-1] or None}
    return None


class NeedScreenshot(RuntimeError):
    """The page could not be read from the server; ask the user for a screenshot."""


def read_listing(url):
    """Returns (listing, calls, page_hash). calls lists the model calls made."""
    url = canonical(url)
    store = store_of(url)
    calls = []
    listing, page_hash, method = None, None, None
    if store["domain"] == "flipkart.com":
        try:
            listing, page_hash = fetch_flipkart(url)
            method = "flipkart page data"
        except requests.RequestException:
            listing = None
    if listing is None:
        pages = tavily.extract([url])
        text = pages.get(url) or next(iter(pages.values()), "")
        if len(text) < 1500:
            pages = tavily.extract([url], depth="advanced")
            text = pages.get(url) or next(iter(pages.values()), "")
        if not text:
            raise ValueError("Could not read that page. Try pasting the listing text instead.")
        page_hash = hashlib.sha1(text.encode()).hexdigest()
        listing, meta = extract_with_model(text, url, store)
        calls.append(meta)
        method = "Tavily extract + " + meta["model"]
        if store["domain"] != "amazon.in":
            truth = structured_offer(url)
            if truth and truth["price_inr"]:
                listing["model_read"] = {"price_inr": listing.get("price_inr"),
                                         "in_stock": listing.get("in_stock")}
                listing["price_inr"] = truth["price_inr"]
                if truth["in_stock"] is not None:
                    listing["in_stock"] = truth["in_stock"]
                    listing["availability_text"] = truth["availability"]
                method += ", verified with page data"
    listing["gpu"] = normalise_gpu(listing.get("title") or "") or \
        normalise_gpu(listing.get("gpu") or "")
    if not listing.get("price_inr"):
        raise NeedScreenshot(f"{store['name']} did not let Asli read this page. "
                             "Upload a screenshot of the listing and Asli will read it instead.")
    listing.update(url=url, store=store["name"], store_domain=store["domain"],
                   store_kind=store["kind"], method=method)
    return listing, calls, page_hash


SCREENSHOT_SYSTEM = ("You read screenshots of Indian e-commerce product pages and return the "
                     "listing facts as JSON. Use only what is visible; use null when a field is "
                     "not shown. Prices are integers in rupees without commas. A 'Notify Me', "
                     "'Coming Soon' or 'Sold Out' button means in_stock is false; 'Buy Now' or "
                     "'Add to Cart' means true. The seller is the name after 'Seller' or 'Sold by'.")


SHOT_FIELDS = """{"title": str, "brand": str|null, "price_inr": int|null, "mrp_inr": int|null,
 "in_stock": bool|null, "availability_text": str|null, "seller": str|null,
 "returnable": bool|null, "rating": float|null, "rating_count": int|null}"""


def read_image(image, url=""):
    """Read a listing from a screenshot (data URL) with Nemotron's vision model."""
    store = store_of(url) if url else {"domain": "", "name": "Screenshot", "kind": "unknown"}
    user = (f"Store (if known): {store['name']}\nURL (if known): {url or 'unknown'}\n\n"
            f"The MRP is the struck-through price. Return only JSON with these fields:\n{SHOT_FIELDS}")
    listing, meta = llm.chat_json("read_screenshot", SCREENSHOT_SYSTEM, user, max_tokens=500,
                                  image=image)
    listing.setdefault("is_product_page", True)
    if not url:
        name = (listing.get("store") or "").lower()
        for domain in ("flipkart", "amazon"):
            if domain in name or domain in (listing.get("title") or "").lower():
                store = store_of(f"https://www.{domain}.{'in' if domain == 'amazon' else 'com'}/")
    listing["gpu"] = normalise_gpu(listing.get("title") or "") or normalise_gpu(listing.get("gpu") or "")
    if not listing.get("price_inr"):
        raise ValueError("Asli could not find a price in that screenshot. Try one that shows "
                         "the title, price and the buy or notify button.")
    listing.update(url=url, store=store["name"], store_domain=store["domain"],
                   store_kind=store["kind"], method="screenshot + " + meta["model"])
    return listing, [meta], hashlib.sha1(image[-4000:].encode()).hexdigest()


def read_text(text, url=""):
    """Fallback when a site blocks us: the user pastes the listing text."""
    store = store_of(url) if url else {"domain": "", "name": "Pasted listing", "kind": "unknown"}
    listing, meta = extract_with_model(text, url or "(pasted)", store)
    listing["gpu"] = normalise_gpu(listing.get("title") or "") or normalise_gpu(listing.get("gpu") or "")
    listing.update(url=url, store=store["name"], store_domain=store["domain"],
                   store_kind=store["kind"], method="pasted text + " + meta["model"])
    return listing, [meta], hashlib.sha1(text.encode()).hexdigest()
