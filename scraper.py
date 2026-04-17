"""
Amazon Price Scraper
Supports: amazon.eg, .com, .sa, .ae, .co.uk, .de, .fr, .it, .es, .co.jp, .ca, amzn.to
"""
import re
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

AMAZON_DOMAINS = re.compile(
    r"(amazon\.(com|eg|sa|ae|co\.uk|de|fr|it|es|co\.jp|ca|com\.au|com\.br|in|"
    r"com\.mx|nl|pl|se|com\.tr|be|sg|com\.sg)|amzn\.(to|eu|asia))",
    re.I
)

CURRENCY_MAP = {
    "amazon.eg":     "EGP",
    "amazon.sa":     "SAR",
    "amazon.ae":     "AED",
    "amazon.com":    "USD",
    "amazon.co.uk":  "GBP",
    "amazon.de":     "EUR",
    "amazon.fr":     "EUR",
    "amazon.it":     "EUR",
    "amazon.es":     "EUR",
    "amazon.co.jp":  "JPY",
    "amazon.ca":     "CAD",
    "amazon.com.au": "AUD",
    "amazon.in":     "INR",
    "amazon.com.br": "BRL",
    "amazon.nl":     "EUR",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


class AmazonScraper:

    def __init__(self):
        self.session = requests.Session()

    def is_amazon_url(self, url: str) -> bool:
        try:
            return bool(AMAZON_DOMAINS.search(urlparse(url).netloc))
        except Exception:
            return False

    def _resolve_short_url(self, url: str) -> str:
        """Expand amzn.to and similar short URLs"""
        try:
            r = self.session.head(url, allow_redirects=True, timeout=10)
            return r.url
        except Exception:
            return url

    def extract_asin(self, url: str) -> str | None:
        patterns = [
            r"/dp/([A-Z0-9]{10})",
            r"/gp/product/([A-Z0-9]{10})",
            r"/product/([A-Z0-9]{10})",
            r"/ASIN/([A-Z0-9]{10})",
            r"[?&]asin=([A-Z0-9]{10})",
        ]
        for pat in patterns:
            m = re.search(pat, url, re.I)
            if m:
                return m.group(1).upper()
        return None

    def _get_currency(self, url: str, soup: BeautifulSoup) -> str:
        try:
            parsed  = urlparse(url)
            domain  = parsed.netloc.lower().replace("www.", "")
            if domain in CURRENCY_MAP:
                return CURRENCY_MAP[domain]
        except Exception:
            pass
        # Try to extract from page
        for sel in ["#corePriceDisplay_desktop_feature_div .a-price-symbol",
                    ".a-price-symbol"]:
            el = soup.select_one(sel)
            if el:
                sym = el.get_text(strip=True)
                sym_map = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY",
                           "₹": "INR", "ج.م": "EGP", "ر.س": "SAR", "د.إ": "AED"}
                if sym in sym_map:
                    return sym_map[sym]
        return "USD"

    def _parse_price(self, text: str) -> float | None:
        """Extract numeric price from text like '1,299.99' or '1.299,99'"""
        if not text:
            return None
        # Remove currency symbols and spaces
        cleaned = re.sub(r"[^\d.,]", "", text.strip())
        if not cleaned:
            return None
        # Handle formats: 1,299.99 or 1.299,99
        if "," in cleaned and "." in cleaned:
            if cleaned.rindex(".") > cleaned.rindex(","):
                cleaned = cleaned.replace(",", "")
            else:
                cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            parts = cleaned.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _extract_price_from_soup(self, soup: BeautifulSoup) -> float | None:
        """Try multiple selectors to find price"""
        # Priority selectors — most reliable first
        selectors = [
            # Core price (main buy box)
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            "#corePrice_desktop .a-offscreen",
            "#price_inside_buybox",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#priceblock_saleprice",
            # Newer layout
            ".a-price.a-text-price.a-size-medium .a-offscreen",
            ".reinventPricePriceToPayMargin .a-offscreen",
            "#apex_desktop .a-offscreen",
            # Fresh/pantry
            "#freshPriceblock_ourprice",
            "#pantryPrice_ourprice",
            # Offer price
            ".a-price .a-offscreen",
            "#price .a-offscreen",
            "span.a-price > span.a-offscreen",
            # Deal price
            "#dealprice_shippingmessage .a-color-price",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                price = self._parse_price(el.get_text(strip=True))
                if price and price > 0:
                    logger.debug(f"  Price found via selector: {sel} → {price}")
                    return price

        # Fallback: JSON-LD structured data
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(tag.string or "")
                if isinstance(data, dict):
                    offers = data.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0]
                    p = offers.get("price") or data.get("price")
                    if p:
                        price = self._parse_price(str(p))
                        if price and price > 0:
                            return price
            except Exception:
                pass

        return None

    def _extract_title(self, soup: BeautifulSoup) -> str:
        selectors = [
            "#productTitle",
            "#title span",
            "h1.a-size-large span",
            "h1 span#productTitle",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                return el.get_text(strip=True)
        return "Unknown Product"

    def _check_availability(self, soup: BeautifulSoup) -> bool:
        unavail_selectors = [
            "#availability span.a-color-price",
            "#outOfStock",
        ]
        for sel in unavail_selectors:
            el = soup.select_one(sel)
            if el and any(kw in el.get_text().lower() for kw in
                          ["unavailable", "غير متاح", "out of stock", "currently unavailable"]):
                return False
        avail_el = soup.select_one("#availability span")
        if avail_el:
            text = avail_el.get_text(strip=True).lower()
            if any(kw in text for kw in ["in stock", "متاح", "available", "توصيل"]):
                return True
            if any(kw in text for kw in ["out of stock", "غير متاح", "unavailable"]):
                return False
        return True  # Assume available if unclear

    def get_product(self, url: str, retries: int = 3) -> dict | None:
        # Resolve short URLs
        if re.search(r"amzn\.(to|eu|asia)", url, re.I):
            url = self._resolve_short_url(url)

        asin = self.extract_asin(url)

        for attempt in range(retries):
            try:
                ua = random.choice(USER_AGENTS)
                headers = {
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Cache-Control": "max-age=0",
                }

                time.sleep(random.uniform(1.5, 3.5))
                resp = self.session.get(url, headers=headers, timeout=20, allow_redirects=True)

                if resp.status_code == 503:
                    logger.warning(f"  503 on attempt {attempt+1}, retrying...")
                    time.sleep(5 * (attempt + 1))
                    continue

                if resp.status_code != 200:
                    logger.warning(f"  HTTP {resp.status_code} for {url[:60]}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Check if Amazon blocked us (CAPTCHA page)
                if soup.find("form", {"action": "/errors/validateCaptcha"}):
                    logger.warning(f"  CAPTCHA on attempt {attempt+1}")
                    time.sleep(10)
                    continue

                title     = self._extract_title(soup)
                price     = self._extract_price_from_soup(soup)
                currency  = self._get_currency(url, soup)
                available = self._check_availability(soup)

                logger.info(f"  ✅ {title[:50]} | {price} {currency}")
                return {
                    "title":     title,
                    "price":     price,
                    "currency":  currency,
                    "available": available,
                    "asin":      asin,
                    "url":       url,
                }

            except requests.exceptions.Timeout:
                logger.warning(f"  Timeout on attempt {attempt+1}")
                time.sleep(3)
            except Exception as e:
                logger.error(f"  Error on attempt {attempt+1}: {e}")
                time.sleep(3)

        logger.error(f"  Failed after {retries} attempts: {url[:60]}")
        return None
