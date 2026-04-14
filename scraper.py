import re
import json
import time
import logging
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlencode, parse_qs

logger = logging.getLogger(__name__)

_scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)

HEADERS = {
    'Accept-Language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
    'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
}

# ─── URL Cleaning ─────────────────────────────────────────────────────────────

def extract_asin(url: str) -> str | None:
    """Extract ASIN from any Amazon URL format."""
    # /dp/ASIN or /gp/product/ASIN or /product/ASIN
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'/product/([A-Z0-9]{10})',
        r'[?&]asin=([A-Z0-9]{10})',
    ]
    for pat in patterns:
        m = re.search(pat, url, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None

def clean_amazon_url(url: str) -> str:
    """Return clean product URL from any Amazon URL. Falls back to original."""
    asin = extract_asin(url)
    if asin:
        # Build clean URL - no tracking params
        return f"https://www.amazon.eg/dp/{asin}"
    return url

def clean_noon_url(url: str) -> str:
    """Strip tracking params from Noon URL."""
    try:
        parsed = urlparse(url)
        # Keep only path, no query
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return url

def detect_platform(url: str) -> str | None:
    u = url.lower()
    if 'amazon' in u:
        return 'amazon'
    if 'noon' in u:
        return 'noon'
    return None

# ─── Price parser ─────────────────────────────────────────────────────────────

def parse_price(text: str) -> float | None:
    if not text:
        return None
    try:
        cleaned = re.sub(r'[^\d.,]', '', text.strip())
        if ',' in cleaned and '.' in cleaned:
            cleaned = cleaned.replace(',', '')
        elif ',' in cleaned and cleaned.index(',') < len(cleaned) - 3:
            cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            cleaned = cleaned.replace(',', '.')
        val = float(cleaned)
        return val if val > 0 else None
    except Exception:
        return None

# ─── Amazon ───────────────────────────────────────────────────────────────────

def scrape_amazon(url: str, retries: int = 3) -> tuple[str | None, float | None]:
    clean_url = clean_amazon_url(url)
    asin = extract_asin(url)
    logger.info(f"Amazon scraping: {clean_url} (ASIN: {asin})")

    for attempt in range(retries):
        try:
            if attempt > 0:
                time.sleep(2 * attempt)

            resp = _scraper.get(clean_url, headers=HEADERS, timeout=15)

            # Detect block
            if resp.status_code == 503 or 'Robot Check' in resp.text or 'api-services-support' in resp.text:
                logger.warning(f"Amazon blocked (attempt {attempt+1})")
                continue

            soup = BeautifulSoup(resp.text, 'lxml')

            # ── Name ──
            name = None
            for tag, attrs in [
                ('span', {'id': 'productTitle'}),
                ('h1',   {'class': re.compile(r'title', re.I)}),
            ]:
                el = soup.find(tag, attrs)
                if el:
                    name = el.get_text(strip=True)[:120]
                    break

            # ── Price (multiple strategies) ──
            price = None

            # Strategy 1: .a-offscreen (most reliable)
            for el in soup.find_all('span', {'class': 'a-offscreen'}):
                p = parse_price(el.get_text())
                if p and p > 10:
                    price = p
                    break

            # Strategy 2: whole + fraction
            if not price:
                whole = soup.find('span', {'class': 'a-price-whole'})
                frac  = soup.find('span', {'class': 'a-price-fraction'})
                if whole:
                    raw = whole.get_text(strip=True).replace(',', '').rstrip('.')
                    if frac:
                        raw += '.' + frac.get_text(strip=True)
                    price = parse_price(raw)

            # Strategy 3: legacy price blocks
            if not price:
                for pid in ('priceblock_ourprice', 'priceblock_dealprice', 'priceblock_saleprice'):
                    el = soup.find(id=pid)
                    if el:
                        price = parse_price(el.get_text())
                        if price:
                            break

            # Strategy 4: JSON-LD
            if not price:
                for script in soup.find_all('script', type='application/ld+json'):
                    try:
                        data = json.loads(script.string or '{}')
                        offers = data.get('offers', {})
                        if isinstance(offers, list):
                            offers = offers[0]
                        p = offers.get('price')
                        if p:
                            price = float(p)
                            break
                    except Exception:
                        pass

            if price:
                return name, price

        except Exception as e:
            logger.error(f"Amazon attempt {attempt+1} error: {e}")

    return None, None

# ─── Noon ─────────────────────────────────────────────────────────────────────

def scrape_noon(url: str, retries: int = 3) -> tuple[str | None, float | None]:
    clean_url = clean_noon_url(url)
    logger.info(f"Noon scraping: {clean_url}")

    for attempt in range(retries):
        try:
            if attempt > 0:
                time.sleep(2 * attempt)

            resp = _scraper.get(clean_url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, 'lxml')

            name  = None
            price = None

            # Strategy 1: __NEXT_DATA__
            next_script = soup.find('script', {'id': '__NEXT_DATA__'})
            if next_script:
                try:
                    data  = json.loads(next_script.string or '{}')
                    props = data.get('props', {}).get('pageProps', {})
                    for path in [['product'], ['catalogItem'], ['item'], ['data', 'product']]:
                        node = props
                        for key in path:
                            node = node.get(key, {}) if isinstance(node, dict) else {}
                        if isinstance(node, dict) and node:
                            name  = node.get('name') or node.get('title') or node.get('displayName')
                            price = node.get('price') or node.get('salePrice') or node.get('currentPrice')
                            if name or price:
                                break
                    if isinstance(price, (int, float)):
                        price = float(price)
                    elif isinstance(price, str):
                        price = parse_price(price)
                    if name:
                        name = str(name)[:120]
                except Exception as e:
                    logger.warning(f"Noon JSON parse error: {e}")

            # Strategy 2: HTML fallback
            if not name:
                h1 = soup.find('h1')
                if h1:
                    name = h1.get_text(strip=True)[:120]

            if not price:
                for qa in ('price', 'priceNow', 'sale-price'):
                    el = soup.find(attrs={'data-qa': qa})
                    if el:
                        price = parse_price(el.get_text())
                        if price:
                            break

            if not price:
                for el in soup.find_all(class_=re.compile(r'\bprice\b', re.I)):
                    p = parse_price(el.get_text())
                    if p and 5 < p < 200_000:
                        price = p
                        break

            if price:
                return name, price

        except Exception as e:
            logger.error(f"Noon attempt {attempt+1} error: {e}")

    return None, None

# ─── Public API ───────────────────────────────────────────────────────────────

def get_price(url: str) -> tuple[str | None, float | None, str | None]:
    """Returns (name, price, platform)."""
    platform = detect_platform(url)
    if platform == 'amazon':
        name, price = scrape_amazon(url)
        return name, price, 'amazon'
    elif platform == 'noon':
        name, price = scrape_noon(url)
        return name, price, 'noon'
    return None, None, None
