"""Integration test: scrape 50 different real e-commerce domains.

Each URL belongs to a unique domain — the kind of competitor sites that a
Shopify merchant would compare prices against.  The test produces a detailed
report that lists:
  * which domains PASSED (price extracted)
  * which domains FAILED (no price)
  * overall success rate
  * breakdown of how each site was fetched (httpx vs Playwright)

Run with:
    cd backend
    PYTHONPATH=src python -m pytest tests/test_50_sites_scrape.py -v -s

Skip in CI:
    PYTHONPATH=src python -m pytest -m "not live"
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from price_radar.application.price_extraction.browser_pool import BrowserPool
from price_radar.application.price_extraction.fetcher import PageFetcher
from price_radar.application.price_extraction.result import ExtractionResult
from price_radar.application.proxy_resolver import ProxyResolver, ProxyTier
from price_radar.infrastructure.config import settings

logger = logging.getLogger(__name__)

# Proxy diagnostics — printed at fixture startup so you can immediately
# see whether the proxy is wired in or not.
_proxy_resolver: ProxyResolver | None = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RATE_LIMIT_DELAY = 1.5  # seconds between requests to same domain

live = pytest.mark.live

# ---------------------------------------------------------------------------
# 50 unique e-commerce domains — real product pages
# ---------------------------------------------------------------------------


@dataclass
class SiteTestURL:
    """One product URL from a unique e-commerce domain."""

    url: str
    domain: str  # short human-readable domain label
    label: str  # product description
    may_fail: bool = False  # bot-blocked / geo-blocked sites


# fmt: off
SITE_URLS: list[SiteTestURL] = [
    # ── Major Marketplaces & Retailers ─────────────────────────────────
    SiteTestURL(
        "https://www.amazon.com/Atomic-Habits-Proven-Build-Break/dp/0735211299",
        "amazon.com", "Atomic Habits Book",
    ),
    SiteTestURL(
        "https://www.ebay.com/itm/314074071401",
        "ebay.com", "Sony WH-1000XM5 Headphones",
    ),
    SiteTestURL(
        "https://www.walmart.com/ip/Keurig-K-Elite-Single-Serve-K-Cup-Pod-Coffee-Maker-Brushed-Slate/225142139",
        "walmart.com", "Keurig K-Elite Coffee Maker",
    ),
    SiteTestURL(
        "https://www.target.com/p/keurig-k-mini-single-serve-k-cup-pod-coffee-maker-black/-/A-53448183",
        "target.com", "Keurig K-Mini Coffee Maker", may_fail=True,
    ),
    SiteTestURL(
        "https://www.bestbuy.com/site/apple-airpods-pro-2nd-generation-with-magsafe-case-usbc-white/6447382.p?skuId=6447382",
        "bestbuy.com", "Apple AirPods Pro 2 USB-C", may_fail=True,
    ),

    # ── Electronics / Tech ─────────────────────────────────────────────
    SiteTestURL(
        "https://www.newegg.com/samsung-1tb-990-pro-nvme-2-0/p/N82E16820147860",
        "newegg.com", "Samsung 990 PRO 1TB SSD", may_fail=True,
    ),
    SiteTestURL(
        "https://www.bhphotovideo.com/c/product/1773884-REG/apple_muqt3ll_a_airpods_pro_2nd_generation.html",
        "bhphotovideo.com", "Apple AirPods Pro 2nd Gen",
    ),
    SiteTestURL(
        "https://www.adorama.com/ac15pmua.html",
        "adorama.com", "Apple iPhone 15 Pro Max",
    ),

    # ── Fashion & Apparel ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
        "nike.com", "Nike Air Force 1 07", may_fail=True,
    ),
    SiteTestURL(
        "https://www.adidas.com/us/ultraboost-5-running-shoes/ID8805.html",
        "adidas.com", "Adidas Ultraboost 5", may_fail=True,
    ),
    SiteTestURL(
        "https://www.nordstrom.com/s/nike-dunk-low-retro-sneaker-men/6553503",
        "nordstrom.com", "Nike Dunk Low Retro Sneaker", may_fail=True,
    ),
    SiteTestURL(
        "https://www.macys.com/shop/product/calvin-klein-mens-slim-fit-wool-blend-overcoat?ID=13464653",
        "macys.com", "Calvin Klein Wool Overcoat", may_fail=True,
    ),
    SiteTestURL(
        "https://www.zappos.com/p/new-balance-fresh-foam-x-880v14/product/9853935",
        "zappos.com", "New Balance Fresh Foam 880v14", may_fail=True,
    ),
    SiteTestURL(
        "https://www.asos.com/us/asos-design/asos-design-oversized-t-shirt-in-black/prd/201534401",
        "asos.com", "ASOS Oversized T-Shirt Black", may_fail=True,
    ),

    # ── Shopify-powered stores ─────────────────────────────────────────
    SiteTestURL(
        "https://www.allbirds.com/products/mens-tree-runners",
        "allbirds.com", "Allbirds Mens Tree Runners",
    ),
    SiteTestURL(
        "https://www.gymshark.com/products/gymshark-crest-t-shirt-black-aw23",
        "gymshark.com", "Gymshark Crest T-Shirt Black", may_fail=True,
    ),
    SiteTestURL(
        "https://www.fashionnova.com/products/classic-high-waist-skinny-jeans-medium-blue",
        "fashionnova.com", "Fashion Nova High Waist Skinny Jeans",
    ),
    SiteTestURL(
        "https://bombas.com/products/womens-gripper-ankle-sock-4-pack",
        "bombas.com", "Bombas Gripper Ankle Sock 4-Pack",
    ),
    SiteTestURL(
        "https://www.brooklinen.com/products/luxe-core-sheet-set",
        "brooklinen.com", "Brooklinen Luxe Core Sheet Set",
    ),
    SiteTestURL(
        "https://www.chubbies.com/products/the-midnight-riders",
        "chubbies.com", "Chubbies The Midnight Riders",
    ),
    SiteTestURL(
        "https://ruggable.com/products/solid-teal-rug",
        "ruggable.com", "Ruggable Solid Teal Rug",
    ),
    SiteTestURL(
        "https://www.stance.com/icon-crew-sock/M311D14ICO.html",
        "stance.com", "Stance Icon Crew Sock",
    ),

    # ── Home & Garden ──────────────────────────────────────────────────
    SiteTestURL(
        "https://www.wayfair.com/furniture/pdp/wade-logan-ailianna-upholstered-bed-w006529937.html",
        "wayfair.com", "Wade Logan Upholstered Bed", may_fail=True,
    ),
    SiteTestURL(
        "https://www.overstock.com/Home-Garden/Safavieh-Handmade-Moroccan-Cambridge-Light-Blue-Ivory-Wool-Rug/7889412/product.html",
        "overstock.com", "Safavieh Moroccan Cambridge Rug", may_fail=True,
    ),
    SiteTestURL(
        "https://www.homedepot.com/p/DEWALT-20V-MAX-Cordless-1-2-in-Drill-Driver-Tool-Only-DCD771B/204279856",
        "homedepot.com", "DEWALT 20V Cordless Drill", may_fail=True,
    ),
    SiteTestURL(
        "https://www.lowes.com/pd/Craftsman-V20-1-2-in-Cordless-Drill-Driver-1-Battery-Included/5014440653",
        "lowes.com", "Craftsman V20 Cordless Drill", may_fail=True,
    ),

    # ── Beauty & Health ────────────────────────────────────────────────
    SiteTestURL(
        "https://www.sephora.com/product/mini-lip-injection-extreme-instant-temporary-lip-plumper-P469370",
        "sephora.com", "Too Faced Lip Injection Extreme", may_fail=True,
    ),
    SiteTestURL(
        "https://www.ulta.com/p/vitamin-enriched-face-base-priming-moisturizer-xlsImpprod5180153",
        "ulta.com", "Bobbi Brown Vitamin Face Base", may_fail=True,
    ),
    SiteTestURL(
        "https://www.bathandbodyworks.com/p/champagne-toast-fine-fragrance-mist-026178187.html",
        "bathandbodyworks.com", "Champagne Toast Fragrance Mist", may_fail=True,
    ),
    SiteTestURL(
        "https://colourpop.com/products/lippie-stix-brink",
        "colourpop.com", "ColourPop Lippie Stix Brink",
    ),

    # ── Sports & Outdoors ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.dickssportinggoods.com/p/yeti-rambler-20-oz-tumbler-with-magslider-lid-16yeturmblr20markup/16yeturmblr20markup",
        "dickssportinggoods.com", "YETI Rambler 20oz Tumbler", may_fail=True,
    ),
    SiteTestURL(
        "https://www.rei.com/product/121184/hydro-flask-standard-mouth-water-bottle-21-fl-oz",
        "rei.com", "Hydro Flask 21oz Water Bottle", may_fail=True,
    ),
    SiteTestURL(
        "https://www.patagonia.com/product/mens-better-sweater-fleece-jacket/25528.html",
        "patagonia.com", "Patagonia Better Sweater Jacket", may_fail=True,
    ),

    # ── Books / Media ──────────────────────────────────────────────────
    SiteTestURL(
        "https://www.barnesandnoble.com/w/atomic-habits-james-clear/1130304630",
        "barnesandnoble.com", "Atomic Habits - B&N",
    ),
    SiteTestURL(
        "https://bookshop.org/p/books/atomic-habits-an-easy-proven-way-to-build-good-habits-break-bad-ones-james-clear/11838549",
        "bookshop.org", "Atomic Habits - Bookshop.org",
    ),

    # ── Grocery & Food ─────────────────────────────────────────────────
    SiteTestURL(
        "https://www.instacart.com/store/costco/product_page/kirkland-signature-organic-extra-virgin-olive-oil-2-l-vrbcl01s4ma",
        "instacart.com", "Kirkland Organic Olive Oil", may_fail=True,
    ),
    SiteTestURL(
        "https://www.iherb.com/pr/optimum-nutrition-gold-standard-100-whey-double-rich-chocolate-5-lbs-2-27-kg/27509",
        "iherb.com", "Optimum Nutrition Whey Protein",
    ),

    # ── Toys & Hobbies ─────────────────────────────────────────────────
    SiteTestURL(
        "https://www.lego.com/en-us/product/orchid-10311",
        "lego.com", "LEGO Orchid 10311", may_fail=True,
    ),

    # ── Pet Supplies ───────────────────────────────────────────────────
    SiteTestURL(
        "https://www.chewy.com/dp/167089",
        "chewy.com", "Blue Buffalo Life Protection Dog Food", may_fail=True,
    ),

    # ── Office / Supplies ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.staples.com/hp-63-black-ink-cartridge-f6u62an-140/product/2723540",
        "staples.com", "HP 63 Black Ink Cartridge", may_fail=True,
    ),

    # ── Crafts / Handmade ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.etsy.com/listing/997583775/2025-2026-planner-planner-2025-2026",
        "etsy.com", "2025-2026 Weekly Planner", may_fail=True,
    ),

    # ── International / Global ─────────────────────────────────────────
    SiteTestURL(
        "https://www.aliexpress.com/item/1005006524842368.html",
        "aliexpress.com", "AliExpress Wireless Earbuds", may_fail=True,
    ),

    # ── DTC / Shopify brands ───────────────────────────────────────────
    SiteTestURL(
        "https://www.away.com/carry-on/f28-aluminum-edition",
        "away.com", "Away Carry-On Aluminum Edition", may_fail=True,
    ),
    SiteTestURL(
        "https://meundies.com/products/boxer-brief",
        "meundies.com", "MeUndies Boxer Brief",
    ),
    SiteTestURL(
        "https://www.skims.com/products/fits-everybody-t-shirt-bra-onyx",
        "skims.com", "SKIMS Fits Everybody T-Shirt Bra", may_fail=True,
    ),

    # ── Vitamins / Supplements ─────────────────────────────────────────
    SiteTestURL(
        "https://www.vitacost.com/garden-of-life-vitamin-code-men",
        "vitacost.com", "Garden of Life Vitamin Code Men", may_fail=True,
    ),

    # ── Furniture / Mattress ───────────────────────────────────────────
    SiteTestURL(
        "https://www.cb2.com/catch-all-storage-bin/s426997",
        "cb2.com", "CB2 Catch-All Storage Bin", may_fail=True,
    ),
    SiteTestURL(
        "https://www.potterybarn.com/products/belgian-flax-linen-duvet-cover-sham/",
        "potterybarn.com", "PB Belgian Flax Linen Duvet", may_fail=True,
    ),

    # ── Cosmetics DTC ──────────────────────────────────────────────────
    SiteTestURL(
        "https://glossier.com/products/boy-brow",
        "glossier.com", "Glossier Boy Brow",
    ),

    # ── Baby / Kids ────────────────────────────────────────────────────
    SiteTestURL(
        "https://www.buybuybaby.com/product/graco-modes-nest2grow-4-in-1-stroller/336725",
        "buybuybaby.com", "Graco Modes 4-in-1 Stroller", may_fail=True,
    ),
]
# fmt: on

# Verify exactly 50 unique domains
assert len(SITE_URLS) == 50, f"Expected 50 URLs, got {len(SITE_URLS)}"
_domains_seen = {s.domain for s in SITE_URLS}
assert len(_domains_seen) == 50, (
    f"Expected 50 unique domains, got {len(_domains_seen)}. "
    f"Duplicates: {[s.domain for s in SITE_URLS if [x.domain for x in SITE_URLS].count(s.domain) > 1]}"
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SiteExtractionResult:
    """Extraction result for a single site."""

    site: SiteTestURL
    html_size: int = 0
    extraction: ExtractionResult | None = None
    error: str | None = None
    fetch_time: float = 0.0
    extract_time: float = 0.0
    fetch_method: str = "none"  # "httpx", "playwright", or "none"
    proxy_tier: str = "direct"  # "direct" or "residential"

    @property
    def success(self) -> bool:
        return self.extraction is not None and self.extraction.success

    @property
    def price(self) -> Decimal | None:
        return self.extraction.current_price if self.extraction else None


# ---------------------------------------------------------------------------
# Fixture — fetch all 50 sites
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def site_results() -> list[SiteExtractionResult]:
    """Fetch all 50 e-commerce sites and extract prices.

    Creates a ``ProxyResolver`` from the ``DECODO_PROXY_URL`` environment
    variable (via ``settings``) and injects it into the ``PageFetcher``.
    If the env var is empty, all requests go direct (no proxy).
    """
    global _proxy_resolver

    # ── Proxy setup ───────────────────────────────────────────────────
    proxy_url = settings.decodo_proxy_url
    _proxy_resolver = ProxyResolver(proxy_url=proxy_url)

    print(f"\n{'=' * 90}")
    print(f"  PROXY CONFIGURATION")
    print(f"{'=' * 90}")
    print(f"  DECODO_PROXY_URL set:  {bool(proxy_url)}")
    if proxy_url:
        # Mask the password in the URL for safe logging
        from urllib.parse import urlparse as _urlparse, urlunparse
        parsed = _urlparse(proxy_url)
        masked = parsed._replace(
            netloc=f"{parsed.username}:****@{parsed.hostname}:{parsed.port}"
        ) if parsed.username else parsed
        print(f"  Proxy endpoint:        {urlunparse(masked)}")
    else:
        print(f"  *** NO PROXY CONFIGURED — all requests will be DIRECT ***")
        print(f"  Set DECODO_PROXY_URL env var to enable residential proxy")
    print(f"  Known residential domains: {sum(1 for s in SITE_URLS if _proxy_resolver.resolve(s.domain) == ProxyTier.RESIDENTIAL)}")
    print(f"  Direct domains:            {sum(1 for s in SITE_URLS if _proxy_resolver.resolve(s.domain) == ProxyTier.DIRECT)}")
    print(f"{'=' * 90}\n")

    # ── Fetcher with proxy ────────────────────────────────────────────
    fetcher = PageFetcher(
        use_playwright=True,
        proxy_resolver=_proxy_resolver,
    )
    results: list[SiteExtractionResult] = []
    last_domain: str = ""

    total_sites = len(SITE_URLS)
    for idx, site in enumerate(SITE_URLS, 1):
        domain = urlparse(site.url).netloc
        if domain == last_domain:
            time.sleep(RATE_LIMIT_DELAY)
        last_domain = domain

        tier = _proxy_resolver.resolve(site.domain).value if _proxy_resolver else "direct"
        print(f"  [{idx}/{total_sites}] Scraping {site.domain:<28} ({tier}) ...", end="", flush=True)

        r = SiteExtractionResult(site=site)

        t0 = time.monotonic()
        try:
            fetch_result, extraction = fetcher.fetch_and_extract(site.url)
            r.fetch_time = fetch_result.fetch_time
            r.fetch_method = fetch_result.method
            r.html_size = fetch_result.html_size
            r.proxy_tier = fetch_result.proxy_tier

            if not fetch_result.success:
                r.error = fetch_result.error or "fetch_failed"
            else:
                r.extraction = extraction
                if not extraction.success:
                    r.error = "extraction_found_no_price"
        except Exception as e:
            r.error = f"fetch_extract_error: {e}"
            r.fetch_time = time.monotonic() - t0

        # Per-site progress logging
        status = "OK" if r.success else "FAIL"
        tier_label = f"[{r.proxy_tier.upper()}]"
        price_str = f"${r.price:.2f}" if r.price else "---"
        print(f" {status} {r.fetch_method:<10} {price_str:>10}  {r.fetch_time:.1f}s  {r.error or ''}")
        logger.info(
            "%s %s %-8s %-28s %-12s %s",
            status, tier_label, r.fetch_method,
            site.domain, price_str, r.error or "",
        )

        results.append(r)

    BrowserPool.shutdown()
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(results: list[SiteExtractionResult]) -> dict:
    """Classify results into passed, failed, httpx, playwright, proxy buckets."""
    passed: list[SiteExtractionResult] = []
    failed: list[SiteExtractionResult] = []
    httpx_sites: list[SiteExtractionResult] = []
    playwright_sites: list[SiteExtractionResult] = []
    direct_sites: list[SiteExtractionResult] = []
    residential_sites: list[SiteExtractionResult] = []

    for r in results:
        if r.success:
            passed.append(r)
        else:
            failed.append(r)

        if r.fetch_method == "httpx":
            httpx_sites.append(r)
        elif r.fetch_method == "playwright":
            playwright_sites.append(r)

        if r.proxy_tier == "residential":
            residential_sites.append(r)
        else:
            direct_sites.append(r)

    return {
        "passed": passed,
        "failed": failed,
        "httpx": httpx_sites,
        "playwright": playwright_sites,
        "direct": direct_sites,
        "residential": residential_sites,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@live
class TestFiftySitesScrape:
    """Scrape 50 different e-commerce domains and report results."""

    # ── Core success-rate assertion ────────────────────────────────────

    def test_overall_success_rate(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """At least 40% of all 50 sites must yield a price."""
        c = _classify(site_results)
        total = len(site_results)
        rate = len(c["passed"]) / total if total else 0.0

        # ── Passed domains list ───────────────────────────────────────
        print(f"\n{'=' * 90}")
        print(f"  50-SITE SCRAPE TEST RESULTS")
        print(f"{'=' * 90}")

        print(f"\n  PASSED DOMAINS ({len(c['passed'])}):")
        print(f"  {'-' * 100}")
        print(
            f"  {'#':<4} {'Domain':<28} {'Method':<12} {'Proxy':<13} "
            f"{'Price':>10} {'Curr':>5} {'Conf':>6} {'Strategies'}"
        )
        print(f"  {'-' * 100}")
        for i, r in enumerate(c["passed"], 1):
            d = r.extraction.to_dict()
            price_str = f"{d['current_price']:.2f}"
            strats = ", ".join(d["strategies_used"])
            print(
                f"  {i:<4} {r.site.domain:<28} {r.fetch_method:<12} "
                f"{r.proxy_tier:<13} "
                f"{price_str:>10} {d['currency']:>5} "
                f"{d['confidence']:>5.0%} {strats}"
            )

        # ── Failed domains list ───────────────────────────────────────
        print(f"\n  FAILED DOMAINS ({len(c['failed'])}):")
        print(f"  {'-' * 100}")
        print(
            f"  {'#':<4} {'Domain':<28} {'Method':<12} {'Proxy':<13} {'Reason'}"
        )
        print(f"  {'-' * 100}")
        for i, r in enumerate(c["failed"], 1):
            if r.error:
                reason = r.error[:55]
            elif r.extraction and not r.extraction.success:
                reason = "extraction found no price"
            else:
                reason = "unknown"
            print(
                f"  {i:<4} {r.site.domain:<28} {r.fetch_method:<12} "
                f"{r.proxy_tier:<13} {reason}"
            )

        # ── Fetch method breakdown ────────────────────────────────────
        print(f"\n  FETCH METHOD BREAKDOWN:")
        print(f"  {'-' * 86}")

        httpx_passed = [r for r in c["httpx"] if r.success]
        httpx_failed = [r for r in c["httpx"] if not r.success]
        pw_passed = [r for r in c["playwright"] if r.success]
        pw_failed = [r for r in c["playwright"] if not r.success]
        none_count = sum(1 for r in site_results if r.fetch_method == "none")

        print(f"  httpx total:       {len(c['httpx']):>3}  "
              f"(passed: {len(httpx_passed)}, failed: {len(httpx_failed)})")
        print(f"  Playwright total:  {len(c['playwright']):>3}  "
              f"(passed: {len(pw_passed)}, failed: {len(pw_failed)})")
        print(f"  No fetch:          {none_count:>3}")

        if c["httpx"]:
            httpx_rate = len(httpx_passed) / len(c["httpx"])
            print(f"  httpx success rate:      {httpx_rate:.1%}")
        if c["playwright"]:
            pw_rate = len(pw_passed) / len(c["playwright"])
            print(f"  Playwright success rate:  {pw_rate:.1%}")

        print(f"\n  httpx passed domains:")
        for r in httpx_passed:
            print(f"    - {r.site.domain}")
        print(f"\n  httpx failed domains:")
        for r in httpx_failed:
            print(f"    - {r.site.domain}")
        print(f"\n  Playwright passed domains:")
        for r in pw_passed:
            print(f"    - {r.site.domain}")
        print(f"\n  Playwright failed domains:")
        for r in pw_failed:
            print(f"    - {r.site.domain}")

        # ── Proxy tier breakdown ───────────────────────────────────────
        print(f"\n  PROXY TIER BREAKDOWN:")
        print(f"  {'-' * 86}")

        direct_passed = [r for r in c["direct"] if r.success]
        direct_failed = [r for r in c["direct"] if not r.success]
        res_passed = [r for r in c["residential"] if r.success]
        res_failed = [r for r in c["residential"] if not r.success]

        print(f"  DIRECT total:        {len(c['direct']):>3}  "
              f"(passed: {len(direct_passed)}, failed: {len(direct_failed)})")
        print(f"  RESIDENTIAL total:   {len(c['residential']):>3}  "
              f"(passed: {len(res_passed)}, failed: {len(res_failed)})")

        if c["direct"]:
            direct_rate = len(direct_passed) / len(c["direct"])
            print(f"  Direct success rate:       {direct_rate:.1%}")
        if c["residential"]:
            res_rate = len(res_passed) / len(c["residential"])
            print(f"  Residential success rate:  {res_rate:.1%}")

        print(f"\n  Residential passed domains:")
        for r in res_passed:
            print(f"    - {r.site.domain} ({r.fetch_method})")
        print(f"\n  Residential failed domains:")
        for r in res_failed:
            print(f"    - {r.site.domain} ({r.fetch_method})")
        print(f"\n  Direct passed domains:")
        for r in direct_passed:
            print(f"    - {r.site.domain} ({r.fetch_method})")
        print(f"\n  Direct failed domains:")
        for r in direct_failed:
            print(f"    - {r.site.domain} ({r.fetch_method})")

        # ── Summary ───────────────────────────────────────────────────
        print(f"\n  {'=' * 86}")
        print(f"  SUMMARY")
        print(f"  {'=' * 86}")
        print(f"  Total sites:           {total}")
        print(f"  Passed (price found):  {len(c['passed'])}")
        print(f"  Failed (no price):     {len(c['failed'])}")
        print(f"  Overall success rate:  {rate:.1%}")
        print(f"  via httpx:             {len(c['httpx'])}")
        print(f"  via Playwright:        {len(c['playwright'])}")
        print(f"  via DIRECT proxy:      {len(c['direct'])}")
        print(f"  via RESIDENTIAL proxy: {len(c['residential'])}")
        print(f"  Proxy configured:      {bool(settings.decodo_proxy_url)}")
        print(f"  {'=' * 86}\n")

        assert rate >= 0.40, (
            f"Success rate {rate:.1%} below 40% threshold. "
            f"Passed {len(c['passed'])}/{total} sites."
        )

    # ── Individual domain detail ──────────────────────────────────────

    def test_detailed_per_site_report(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """Print per-site detail table (always passes)."""
        print(f"\n{'=' * 145}")
        print(
            f"  {'#':<4} {'Domain':<28} {'Label':<30} {'Method':<12} "
            f"{'Proxy':<13} {'Price':>10} {'Curr':>5} {'Conf':>6} "
            f"{'Time':>7} {'Strategies'}"
        )
        print(f"{'=' * 145}")

        for i, r in enumerate(site_results, 1):
            method = r.fetch_method
            tier = r.proxy_tier
            if r.error and method == "none":
                print(
                    f"  {i:<4} {r.site.domain:<28} {r.site.label:<30} "
                    f"{'---':<12} {tier:<13} {'FAIL':>10} {'':>5} "
                    f"{'':>6} {r.fetch_time:>6.1f}s {r.error[:35]}"
                )
            elif r.success:
                d = r.extraction.to_dict()
                price_str = f"{d['current_price']:.2f}"
                strats = ", ".join(d["strategies_used"])
                print(
                    f"  {i:<4} {r.site.domain:<28} {r.site.label:<30} "
                    f"{method:<12} {tier:<13} {price_str:>10} "
                    f"{d['currency']:>5} {d['confidence']:>5.0%} "
                    f"{r.fetch_time:>6.1f}s {strats}"
                )
            else:
                reason = ""
                if r.error:
                    reason = r.error[:35]
                elif r.extraction:
                    reason = "no price found"
                print(
                    f"  {i:<4} {r.site.domain:<28} {r.site.label:<30} "
                    f"{method:<12} {tier:<13} {'FAIL':>10} {'':>5} "
                    f"{'':>6} {r.fetch_time:>6.1f}s {reason}"
                )

        print(f"{'=' * 145}\n")

    # ── Data quality ──────────────────────────────────────────────────

    def test_prices_are_positive(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """All extracted prices must be positive."""
        for r in site_results:
            if r.success and r.price is not None:
                assert r.price > 0, (
                    f"Non-positive price for {r.site.domain}: {r.price}"
                )

    def test_fetch_method_is_valid(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """fetch_method must be 'httpx', 'playwright', or 'none'."""
        valid = {"httpx", "playwright", "none"}
        for r in site_results:
            assert r.fetch_method in valid, (
                f"Invalid fetch_method '{r.fetch_method}' for {r.site.domain}"
            )

    def test_no_duplicate_domains(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """Verify all 50 sites are unique domains."""
        domains = [r.site.domain for r in site_results]
        assert len(domains) == len(set(domains)), "Duplicate domains detected"

    def test_confidence_scores_valid(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """Confidence scores must be in [0, 1] range."""
        for r in site_results:
            if r.success and r.extraction:
                assert 0.0 <= r.extraction.confidence <= 1.0, (
                    f"Confidence {r.extraction.confidence} out of range "
                    f"for {r.site.domain}"
                )

    def test_may_fail_sites_flagged(
        self, site_results: list[SiteExtractionResult]
    ) -> None:
        """Count how many may_fail sites actually failed (informational)."""
        may_fail_sites = [r for r in site_results if r.site.may_fail]
        may_fail_failed = [r for r in may_fail_sites if not r.success]
        reliable_sites = [r for r in site_results if not r.site.may_fail]
        reliable_failed = [r for r in reliable_sites if not r.success]

        print(f"\n  may_fail sites: {len(may_fail_failed)}/{len(may_fail_sites)} failed")
        print(f"  reliable sites: {len(reliable_failed)}/{len(reliable_sites)} failed")

        if reliable_failed:
            print("  Reliable sites that failed:")
            for r in reliable_failed:
                print(f"    - {r.site.domain}: {r.error or 'no price found'}")
