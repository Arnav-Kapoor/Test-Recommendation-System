"""
SHL Product Catalog Scraper — Concurrent Version
==================================================
Bypasses CloudFront bot protection using playwright-stealth.
Detail pages are scraped concurrently using asyncio.gather
with a semaphore to limit parallel tabs.

Install:
    pip install playwright beautifulsoup4 playwright-stealth
    playwright install chromium

Run:
    python shl_scraper.py
"""

import asyncio
import json
import random
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urljoin
from playwright.async_api import async_playwright, Browser, BrowserContext
try:
    from playwright_stealth import Stealth
    USE_NEW_STEALTH = True
except ImportError:
    from playwright_stealth import stealth_async
    USE_NEW_STEALTH = False
from bs4 import BeautifulSoup


# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════

BASE_URL              = "https://www.shl.com/products/product-catalog/"
ROWS_PER_PAGE         = 12
REQUEST_DELAY         = 1.0        # seconds between page-level requests
HEADLESS              = False      # set True once confirmed working
DEBUG                 = False      # set True to see cookie debug output

MAX_PAGES_PREPACKAGED = 12
MAX_PAGES_INDIVIDUAL  = 32

# How many detail pages to scrape at the same time.
# 3-5 is a safe range — too high risks getting blocked.
CONCURRENT_DETAILS    = 4

HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer":         "https://www.google.com/",
}


# ══════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════

@dataclass
class ProductDetail:
    url: str
    title: str
    description: str
    job_levels: list[str]
    languages: list[str]
    assessment_length: str
    full_text: str


@dataclass
class Product:
    name: str
    url: str
    remote_testing: bool
    adaptive_irt: bool
    test_types: list[str]
    category: str
    detail: Optional[ProductDetail] = None


TEST_TYPE_LABELS = {
    "A": "Ability & Aptitude",
    "B": "Biodata & Situational Judgement",
    "C": "Competencies",
    "D": "Development & 360",
    "E": "Assessment Exercises",
    "K": "Knowledge & Skills",
    "P": "Personality & Behavior",
    "S": "Simulations",
}


# ══════════════════════════════════════════════════════════════
#  STEALTH BROWSER SETUP
# ══════════════════════════════════════════════════════════════

async def new_stealth_context(browser: Browser) -> BrowserContext:
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers=HEADERS,
    )
    return context


async def apply_stealth(page) -> None:
    if USE_NEW_STEALTH:
        await Stealth().apply_stealth_async(page)
    else:
        await stealth_async(page)


async def fetch_html(context: BrowserContext, url: str) -> str:
    page = await context.new_page()
    try:
        await apply_stealth(page)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(random.uniform(0.5, 1.0))
        html = await page.content()
        if "403 ERROR" in html or "Request blocked" in html:
            print(f"    403 blocked on {url}. Try increasing REQUEST_DELAY.")
        return html
    finally:
        await page.close()


# ══════════════════════════════════════════════════════════════
#  TABLE PARSER
# ══════════════════════════════════════════════════════════════

def parse_table(soup: BeautifulSoup, category: str) -> list[Product]:
    keyword = "Pre-packaged" if category == "Pre-packaged" else "Individual Test"

    target_table = None
    for table in soup.find_all("table"):
        first_th = table.find("th")
        if first_th and keyword in first_th.get_text():
            target_table = table
            break

    if not target_table:
        all_tables = soup.find_all("table")
        idx = 0 if category == "Pre-packaged" else 1
        if len(all_tables) > idx:
            target_table = all_tables[idx]

    if not target_table:
        if DEBUG:
            body = soup.find("body")
            print(f"    No table found. Page preview: {body.get_text()[:300] if body else 'empty'}")
        return []

    products = []
    for row in target_table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        anchor = cols[0].find("a")
        if not anchor:
            continue

        name       = anchor.get_text(strip=True)
        href       = anchor.get("href", "")
        url        = urljoin("https://www.shl.com", href)
        remote     = bool(cols[1].find(["img", "svg", "span"]) or cols[1].get_text(strip=True))
        adaptive   = bool(cols[2].find(["img", "svg", "span"]) or cols[2].get_text(strip=True))
        raw_types  = cols[3].get_text(separator=" ", strip=True).split()
        test_types = [t for t in raw_types if t in TEST_TYPE_LABELS]

        products.append(Product(
            name=name, url=url,
            remote_testing=remote, adaptive_irt=adaptive,
            test_types=test_types, category=category,
        ))

    return products


# ══════════════════════════════════════════════════════════════
#  COOKIE BANNER
# ══════════════════════════════════════════════════════════════

COOKIE_SELECTORS = [
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "button#onetrust-accept-btn-handler",
    "button:has-text('Accept All')",
    "button:has-text('Allow All')",
    "button:has-text('I Accept')",
]

COOKIE_IDS_TO_STRIP = [
    "CybotCookiebotDialog",
    "CybotCookiebotDialogBodyUnderlay",
    "CybotCookiebotDialogBody",
    "CybotCookiebotDialogBodyContent",
    "onetrust-consent-sdk",
    "onetrust-banner-sdk",
]

COOKIE_TEXT_PREFIXES = (
    "this website uses cookies",
    "we use cookies",
    "by clicking",
    "cookie policy",
)


async def dismiss_cookie_banner(page) -> None:
    await page.wait_for_timeout(2000)

    if DEBUG:
        found = await page.evaluate(
            "() => !!document.getElementById('CybotCookiebotDialog')"
        )
        print(f"      [cookie] dialog in DOM: {found}")

    for selector in COOKIE_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                print(f"      Cookie banner dismissed")
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue

    # Fallback: check inside iframes
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        for selector in COOKIE_SELECTORS:
            try:
                btn = frame.locator(selector).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    print(f"      Cookie banner dismissed (iframe)")
                    await page.wait_for_timeout(1000)
                    return
            except Exception:
                continue


def strip_cookie_elements(soup: BeautifulSoup) -> None:
    """Remove all cookie-related elements from parsed HTML."""
    for el_id in COOKIE_IDS_TO_STRIP:
        el = soup.find(id=el_id)
        if el:
            el.decompose()

    for tag in soup.find_all(True):
        try:
            text = tag.get_text(strip=True).lower()
            if text.startswith(COOKIE_TEXT_PREFIXES):
                tag.decompose()
        except Exception:
            continue


# ══════════════════════════════════════════════════════════════
#  DETAIL PAGE — wrapped in semaphore for concurrency control
# ══════════════════════════════════════════════════════════════

async def scrape_detail(
    context: BrowserContext,
    product: Product,
    semaphore: asyncio.Semaphore,
) -> ProductDetail:
    async with semaphore:
        page = await context.new_page()
        try:
            await apply_stealth(page)
            await page.goto(product.url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            await dismiss_cookie_banner(page)

            try:
                await page.wait_for_selector("h1", timeout=8000)
            except Exception:
                pass

            await page.wait_for_timeout(1500)
            html = await page.content()
        finally:
            await page.close()

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()

    strip_cookie_elements(soup)

    main = (
        soup.find("main")
        or soup.find(class_="entry-content")
        or soup.find(id="content")
        or soup
    )

    title      = main.find("h1") or soup.find("h1")
    title_text = title.get_text(strip=True) if title else product.name

    def get_section_text(heading_text: str) -> str:
        """Find an <h4> by its text and return the text of the next sibling element."""
        for h4 in main.find_all("h4"):
            if heading_text.lower() in h4.get_text(strip=True).lower():
                sibling = h4.find_next_sibling()
                if sibling:
                    return sibling.get_text(separator=" ", strip=True)
                # Sometimes content is directly after the h4 with no wrapper tag
                text = h4.next_sibling
                if text:
                    return str(text).strip()
        return ""

    def get_section_list(heading_text: str) -> list[str]:
        """Get comma-separated values under a heading as a clean list."""
        raw = get_section_text(heading_text)
        return [v.strip() for v in raw.split(",") if v.strip()]

    description     = get_section_text("Description")
    job_levels      = get_section_list("Job levels")
    languages       = get_section_list("Languages")

    # Assessment length — extract just the number if present
    raw_length      = get_section_text("Assessment length")
    import re
    match           = re.search(r"\d+", raw_length)
    assessment_length = match.group(0) + " minutes" if match else raw_length

    lines     = [l for l in main.get_text("\n", strip=True).splitlines() if l.strip()]
    full_text = "\n".join(lines)

    return ProductDetail(
        url=product.url,
        title=title_text,
        description=description,
        job_levels=job_levels,
        languages=languages,
        assessment_length=assessment_length,
        full_text=full_text,
    )


# ══════════════════════════════════════════════════════════════
#  PAGINATION LOOP — detail pages scraped concurrently per page
# ══════════════════════════════════════════════════════════════

async def scrape_table(
    context: BrowserContext,
    category: str,
    type_param: str,
    max_pages: int,
    scrape_details: bool,
    semaphore: asyncio.Semaphore,
) -> list[Product]:
    all_products = []

    for page_num in range(max_pages):
        start = page_num * ROWS_PER_PAGE
        url   = f"{BASE_URL}?start={start}&type=1&{type_param}"
        print(f"\n  [{category}] Page {page_num + 1}/{max_pages} (start={start})")

        html     = await fetch_html(context, url)
        soup     = BeautifulSoup(html, "html.parser")
        products = parse_table(soup, category)

        if not products:
            print("    No products found — stopping early.")
            break

        print(f"    {len(products)} products found")

        if scrape_details:
            # Scrape all detail pages on this listing page concurrently
            tasks = [
                scrape_detail(context, product, semaphore)
                for product in products
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for product, result in zip(products, results):
                if isinstance(result, Exception):
                    print(f"    Detail failed for {product.name}: {result}")
                else:
                    product.detail = result
                    print(f"    Done: {product.name}")

        all_products.extend(products)
        await asyncio.sleep(REQUEST_DELAY)

    return all_products


# ══════════════════════════════════════════════════════════════
#  ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

async def scrape_shl(scrape_details: bool = True) -> list[Product]:
    # Semaphore shared across all tasks — caps concurrent browser tabs
    semaphore = asyncio.Semaphore(CONCURRENT_DETAILS)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await new_stealth_context(browser)

        # print("\nScraping Pre-packaged Job Solutions...")
        # prepackaged = await scrape_table(
        #     context, "Pre-packaged", "type=2",
        #     MAX_PAGES_PREPACKAGED, scrape_details, semaphore,
        # )

        print("\nScraping Individual Test Solutions...")
        individual = await scrape_table(
            context, "Individual Test", "type=1",
            MAX_PAGES_INDIVIDUAL, scrape_details, semaphore,
        )

        await browser.close()

    return individual


# ══════════════════════════════════════════════════════════════
#  GEN AI OUTPUT
# ══════════════════════════════════════════════════════════════

def to_llm_documents(products: list[Product], max_chars: int = 4000) -> list[dict]:
    return [
        {
            "title":             p.name,
            "source":            p.url,
            "category":          p.category,
            "remote_testing":    p.remote_testing,
            "adaptive_irt":      p.adaptive_irt,
            "test_types":        [TEST_TYPE_LABELS.get(t, t) for t in p.test_types],
            "description":       p.detail.description if p.detail else "",
            "job_levels":        p.detail.job_levels if p.detail else [],
            "languages":         p.detail.languages if p.detail else [],
            "assessment_length": p.detail.assessment_length if p.detail else "",
            "content":           p.detail.full_text[:max_chars] if p.detail else "",
        }
        for p in products
    ]


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

async def main():
    print("SHL Product Catalog Scraper - Concurrent Stealth Mode")
    print(f"Concurrent detail pages: {CONCURRENT_DETAILS}")

    QUICK_TEST  = False   # set False for full scrape
    GET_DETAILS = True

    global MAX_PAGES_PREPACKAGED, MAX_PAGES_INDIVIDUAL
    if QUICK_TEST:
        MAX_PAGES_PREPACKAGED = 1
        MAX_PAGES_INDIVIDUAL  = 1
        GET_DETAILS = True
        print("Quick test mode: 1 page per table\n")

    products = await scrape_shl(scrape_details=GET_DETAILS)

    print(f"\nTotal products scraped: {len(products)}")

    if not products:
        print("\nNothing scraped.")
        print("  1. Make sure playwright-stealth is installed: pip install playwright-stealth")
        print("  2. Set HEADLESS=False to watch the browser")
        print("  3. Increase REQUEST_DELAY")
        return

    with open("shl_products.json", "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in products], f, indent=2, ensure_ascii=False)
    print("Saved -> shl_products.json")

    docs = to_llm_documents(products)
    with open("shl_llm_documents.json", "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
    print(f"Saved -> shl_llm_documents.json ({len(docs)} docs)")

    p = products[0]
    print(f"\n--- Sample ---")
    print(f"Name:        {p.name}")
    print(f"Category:    {p.category}")
    print(f"Test Types:  {p.test_types}")
    if p.detail:
        print(f"Description: {p.detail.description[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())