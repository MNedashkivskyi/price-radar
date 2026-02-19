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

logger = logging.getLogger(__name__)

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
        "https://www.bhphotovideo.com/c/product/1904850-REG/lenovo_82xq00ebus_15_6_ideapad_slim_3.html",
        "bhphotovideo.com", "Lenovo 15.6 IdeaPad Slim 3 Notebook",
    ),
    SiteTestURL(
        "https://www.adorama.com/ihas1f8ataba.html",
        "adorama.com", "HP Elite Mini 800 G9 Desktop Mini PC",
    ),

    # ── Fashion & Apparel ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
        "nike.com", "Nike Air Force 1 07", may_fail=True,
    ),
    SiteTestURL(
        "https://www.adidas.com/us/adizero-evo-sl-atr-shoes/KK2683.html",
        "adidas.com", "ADIZERO EVO SL ATR Shoes", may_fail=True,
    ),
    SiteTestURL(
        "https://www.nordstrom.com/s/vuori-sunday-performance-joggers/5401058?origin=category-personalizedsort&breadcrumb=Home%2FMen%2FClothing%2FActivewear&color=001",
        "nordstrom.com", "Nike Dunk Low Retro Sneaker", may_fail=True,
    ),
    SiteTestURL(
        "https://www.macys.com/shop/product/lacoste-mens-elastic-waistband-trunks-3-pack?ID=25196510",
        "macys.com", "Men's Elastic Waistband Trunks, 3-Pack", may_fail=True,
    ),
    SiteTestURL(
        "https://www.zappos.com/p/mens-hoka-bondi-9-drizzle-downpour/product/9984272/color/1112492?zlfid=191&ref=pd_search_nr-1-bqcp_1",
        "zappos.com", "Bondi 9", may_fail=True,
    ),
    SiteTestURL(
        "https://www.asos.com/us/asos-design/asos-design-loose-straight-jeans-in-dark-wash-blue/prd/209998529#colourWayId-209998539",
        "asos.com", "ASOS DESIGN loose straight jeans in dark wash blue", may_fail=True,
    ),

    # ── Shopify-powered stores ─────────────────────────────────────────
    SiteTestURL(
        "https://www.allbirds.com/products/mens-tree-runners",
        "allbirds.com", "Allbirds Mens Tree Runners",
    ),
    SiteTestURL(
        "https://www.gymshark.com/products/gymshark-power-t-shirt-ss-tops-black-aw25-3",
        "gymshark.com", "Gymshark Crest T-Shirt Black", may_fail=True,
    ),
    SiteTestURL(
        "https://www.fashionnova.com/products/classic-high-waist-skinny-jeans-medium-blue",
        "fashionnova.com", "Fashion Nova High Waist Skinny Jeans",
    ),
    SiteTestURL(
        "https://bombas.com/products/mens-cotton-modal-blend-boxer-brief-classic-fly-3-pack?variant=olive-spice-mix&size=l",
        "bombas.com", "Men's Cotton Modal Blend Boxer Brief 6 3-Pack",
    ),
    SiteTestURL(
        "https://www.brooklinen.com/products/luxe-core-sheet-set",
        "brooklinen.com", "Brooklinen Luxe Core Sheet Set",
    ),
    SiteTestURL(
        "chubbiesshorts.com/collections/the-swim-trunks?filter.product_style=Classic%20Swim",
        "chubbies.com", "The Whale Sharks",
    ),
    SiteTestURL(
        "https://ruggable.com/products/gisele-neutral-navy-tufted-rug?size=8x10&system=rug-cvr",
        "ruggable.com", "Navy Rug",
    ),
    SiteTestURL(
        "https://eu.stance.com/collections/mens-casual-socks/products/prep-stripe-sock-3-pack-pale-blue",
        "stance.com", "PREP STRIPE SOCK 3 PACK",
    ),

    # ── Home & Garden ──────────────────────────────────────────────────
    SiteTestURL(
        "https://www.wayfair.com/furniture/pdp/willa-arlo-interiors-duncanville-upholstered-platform-bed-w011410274.html?piid=1382240518%2C1382240519",
        "wayfair.com", "Duncanville Upholstered King Platform Bed, Black", may_fail=True,
    ),
    SiteTestURL(
        "https://www.overstock.com/Home-Garden/Comfy-Cloud-Couch-Plush-Modular-Sectional-Sofa-For-Living-Room/43594621/product.html?refccid=6HCMMYANUBBYXM6U7M7QOK4WMQ&searchidx=0",
        "overstock.com", "Comfy Cloud Couch Plush Modular Sectional Sofa For Living Room", may_fail=True,
    ),
    SiteTestURL(
        "https://www.homedepot.com/p/DEWALT-20V-MAX-Cordless-1-2-in-Drill-Driver-Tool-Only-DCD771B/204279856",
        "homedepot.com", "DEWALT 20V Cordless Drill", may_fail=True,
    ),
    SiteTestURL(
        "https://www.lowes.com/pd/allen-roth-White-Drop-In-Rectangular-Bathroom-Sink-with-Overflow-Drain-21-26-in-x-18-5-in/5006032601",
        "lowes.com", "allen + roth Ramsgate Vitreous China 18.5-in Drop-in", may_fail=True,
    ),

    # ── Beauty & Health ────────────────────────────────────────────────
    SiteTestURL(
        "https://www.sephora.com/product/kiehls-mini-better-screen-tm-uv-serum-spf-50-facial-sunscreen-with-collagen-peptide-P510286?skuId=2734804&icid2=homepage_productlist_chosenforyou_us_ufe_092022",
        "sephora.com", "Mini Better Screen™ UV ", may_fail=True,
    ),
    SiteTestURL(
        "https://www.ulta.com/p/platinum-blow-dry-spray-xlsImpprod6370237?sku=2233328",
        "ulta.com", "Platinum Blow-Dry Spray", may_fail=True,
    ),
    SiteTestURL(
        "https://www.bathandbodyworks.com/p/lifes-a-fairytale-3-wick-candle-028026402",
        "bathandbodyworks.com", "Life's a Fairytale", may_fail=True,
    ),
    SiteTestURL(
        "https://colourpop.com/products/thats-taupe-eyeshadow-palette",
        "colourpop.com", "9-Pan Palette",
    ),

    # ── Sports & Outdoors ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.rei.com/product/249302/kuhl-remi-pullover-hoody-womens",
        "rei.com", "Remi Pullover Hoody", may_fail=True,
    ),
    SiteTestURL(
        "https://www.patagonia.com/product/mens-better-sweater-fleece-jacket/25528.html",
        "patagonia.com", "Patagonia Better Sweater Jacket", may_fail=True,
    ),

    # ── Books / Media ──────────────────────────────────────────────────
    SiteTestURL(
        "https://www.barnesandnoble.com/w/heated-rivalry-rachel-reid/1129486546?ean=9781335534637",
        "barnesandnoble.com", "Heated Rivalry",
    ),
    SiteTestURL(
        "https://bookshop.org/p/books/a-hymn-to-life-shame-has-to-change-sides-gis-le-pelicot/97889ab17382bc9b?ean=9798217181339&next=t",
        "bookshop.org", "A Hymn to Life",
    ),

    # ── Grocery & Food ─────────────────────────────────────────────────
    SiteTestURL(
        "https://www.instacart.com/store/costco-business-center/products/43905144-pom-wonderful-100-pomegranate-juice-64-fl-oz",
        "instacart.com", "POM Wonderful 100%", may_fail=True,
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
        "https://www.staples.com/hp-omnidesk-slim-desktop-computer-intel-core-i3-14100-8gb-ram-256gb-ssd-windows-11-home-mouse-keyboard-included/product_24632698?utility=Y",
        "staples.com", "HP 63 Black Ink Cartridge", may_fail=True,
    ),

    # ── Crafts / Handmade ──────────────────────────────────────────────
    SiteTestURL(
        "https://www.etsy.com/pl/listing/521652981/spersonalizowane-may-krolik-rodziny?external=1&ref=hp_consolidated_gifting_listings-3&sts=1&logging_key=ab01ecf512d2bc0b7dd1b738eef8fd46b32c3b59%3A521652981&variation0=1733737902",
        "etsy.com", "2025-2026 Weekly Planner", may_fail=True,
    ),

    # ── International / Global ─────────────────────────────────────────
    SiteTestURL(
        "https://pl.aliexpress.com/item/1005009964962375.html?spm=a2g0o.detail.pcDetailBottomMoreOtherSeller.1.2b1dElQDElQDhP&gps-id=pcDetailBottomMoreOtherSeller&scm=1007.40050.354490.0&scm_id=1007.40050.354490.0&scm-url=1007.40050.354490.0&pvid=a85c1ae2-f66e-4360-9f9f-bde5f492e9f5&_t=gps-id:pcDetailBottomMoreOtherSeller,scm-url:1007.40050.354490.0,pvid:a85c1ae2-f66e-4360-9f9f-bde5f492e9f5,tpp_buckets:668%232846%238113%231998&pdp_ext_f=%7B%22order%22%3A%22331%22%2C%22spu_best_type%22%3A%22price%22%2C%22eval%22%3A%221%22%2C%22sceneId%22%3A%2230050%22%2C%22fromPage%22%3A%22recommend%22%7D&pdp_npi=6%40dis%21PLN%2173.05%2162.93%21%21%21137.76%21118.65%21%40210391a017713595213287270e9a7b%2112000050706713282%21rec%21PL%21%21ABX%211%210%21n_tag%3A-29910%3Bd%3Ac5c180c8%3Bm03_new_user%3A-29895%3BpisId%3A5000000201191184&utparam-url=scene%3ApcDetailBottomMoreOtherSeller%7Cquery_from%3A%7Cx_object_id%3A1005009964962375%7C_p_origin_prod%3A",
        "aliexpress.com", "AliExpress Wireless Earbuds", may_fail=True,
    ),

    # ── DTC / Shopify brands ───────────────────────────────────────────
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
        "https://www.cb2.com/tide-95-teak-outdoor-sofa-with-ivory-sunbrella-cushions/s511909",
        "cb2.com", "CB2 Catch-All Storage Bin", may_fail=True,
    ),
    SiteTestURL(
        "https://www.potterybarn.co.uk/cayman-upholstered-wood-bed?quantity=1&attribute_1=King&attribute_2=Performance%20Boucle%2C%20Oatmeal",
        "potterybarn.com", "PB Belgian Flax Linen Duvet", may_fail=True,
    ),

    # ── Cosmetics DTC ──────────────────────────────────────────────────
    SiteTestURL(
        "https://glossier.com/products/boy-brow",
        "glossier.com", "Glossier Boy Brow",
    ),

    # ── Baby / Kids ────────────────────────────────────────────────────
    SiteTestURL(
        "https://buybuybaby.bedbathandbeyond.com/Baby/Shyft-Intuiti-Travel-System-with-Revolve180-LiteMax-NXT-Rotational-Infant-Car-Seat/42548076/product.html?refccid=TMYFL7K5UV5JDCKNHY5H3KFQ4A&searchidx=0&option=88821863",
        "buybuybaby.com", "Graco Modes 4-in-1 Stroller", may_fail=True,
    ),
]
# fmt: on

# Verify exactly 50 unique domains
assert len(SITE_URLS) == 48, f"Expected 50 URLs, got {len(SITE_URLS)}"
_domains_seen = {s.domain for s in SITE_URLS}
assert len(_domains_seen) == 48, (
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
    """Fetch all 50 e-commerce sites and extract prices."""
    fetcher = PageFetcher(use_playwright=True)
    results: list[SiteExtractionResult] = []
    last_domain: str = ""

    for site in SITE_URLS:
        domain = urlparse(site.url).netloc
        if domain == last_domain:
            time.sleep(RATE_LIMIT_DELAY)
        last_domain = domain

        r = SiteExtractionResult(site=site)

        t0 = time.monotonic()
        try:
            fetch_result, extraction = fetcher.fetch_and_extract(site.url)
            r.fetch_time = fetch_result.fetch_time
            r.fetch_method = fetch_result.method
            r.html_size = fetch_result.html_size

            if not fetch_result.success:
                r.error = fetch_result.error or "fetch_failed"
            else:
                r.extraction = extraction if extraction.success else extraction
                if not extraction.success:
                    r.extraction = extraction  # keep partial data
        except Exception as e:
            r.error = f"fetch_extract_error: {e}"
            r.fetch_time = time.monotonic() - t0

        results.append(r)

    BrowserPool.shutdown()
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(results: list[SiteExtractionResult]) -> dict:
    """Classify results into passed, failed, httpx, playwright buckets."""
    passed: list[SiteExtractionResult] = []
    failed: list[SiteExtractionResult] = []
    httpx_sites: list[SiteExtractionResult] = []
    playwright_sites: list[SiteExtractionResult] = []

    for r in results:
        if r.success:
            passed.append(r)
        else:
            failed.append(r)

        if r.fetch_method == "httpx":
            httpx_sites.append(r)
        elif r.fetch_method == "playwright":
            playwright_sites.append(r)

    return {
        "passed": passed,
        "failed": failed,
        "httpx": httpx_sites,
        "playwright": playwright_sites,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@live
class TestFiftySitesScrape:
    """Scrape 50 different e-commerce domains and report results."""

    # ── Core success-rate assertion ────────────────────────────────────

    def test_1(self):
        from price_radar.infrastructure.config import settings
        print(f"Proxy URL configured: {bool(settings.decodo_proxy_url)}")

        from price_radar.application.proxy_resolver import ProxyResolver
        resolver = ProxyResolver(proxy_url=settings.decodo_proxy_url)
        print(resolver.get_tier_info("amazon.com"))

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
        print(f"  {'-' * 86}")
        print(
            f"  {'#':<4} {'Domain':<28} {'Method':<12} "
            f"{'Price':>10} {'Curr':>5} {'Conf':>6} {'Strategies'}"
        )
        print(f"  {'-' * 86}")
        for i, r in enumerate(c["passed"], 1):
            d = r.extraction.to_dict()
            price_str = f"{d['current_price']:.2f}"
            strats = ", ".join(d["strategies_used"])
            print(
                f"  {i:<4} {r.site.domain:<28} {r.fetch_method:<12} "
                f"{price_str:>10} {d['currency']:>5} "
                f"{d['confidence']:>5.0%} {strats}"
            )

        # ── Failed domains list ───────────────────────────────────────
        print(f"\n  FAILED DOMAINS ({len(c['failed'])}):")
        print(f"  {'-' * 86}")
        print(
            f"  {'#':<4} {'Domain':<28} {'Method':<12} {'Reason'}"
        )
        print(f"  {'-' * 86}")
        for i, r in enumerate(c["failed"], 1):
            if r.error:
                reason = r.error[:60]
            elif r.extraction and not r.extraction.success:
                reason = "extraction found no price"
            else:
                reason = "unknown"
            print(
                f"  {i:<4} {r.site.domain:<28} {r.fetch_method:<12} {reason}"
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
        print(f"\n{'=' * 130}")
        print(
            f"  {'#':<4} {'Domain':<28} {'Label':<35} {'Method':<12} "
            f"{'Price':>10} {'Curr':>5} {'Conf':>6} {'Time':>7} {'Strategies'}"
        )
        print(f"{'=' * 130}")

        for i, r in enumerate(site_results, 1):
            method = r.fetch_method
            if r.error and method == "none":
                print(
                    f"  {i:<4} {r.site.domain:<28} {r.site.label:<35} "
                    f"{'---':<12} {'FAIL':>10} {'':>5} {'':>6} "
                    f"{r.fetch_time:>6.1f}s {r.error[:40]}"
                )
            elif r.success:
                d = r.extraction.to_dict()
                price_str = f"{d['current_price']:.2f}"
                strats = ", ".join(d["strategies_used"])
                print(
                    f"  {i:<4} {r.site.domain:<28} {r.site.label:<35} "
                    f"{method:<12} {price_str:>10} {d['currency']:>5} "
                    f"{d['confidence']:>5.0%} {r.fetch_time:>6.1f}s {strats}"
                )
            else:
                reason = ""
                if r.error:
                    reason = r.error[:40]
                elif r.extraction:
                    reason = "no price found"
                print(
                    f"  {i:<4} {r.site.domain:<28} {r.site.label:<35} "
                    f"{method:<12} {'FAIL':>10} {'':>5} {'':>6} "
                    f"{r.fetch_time:>6.1f}s {reason}"
                )

        print(f"{'=' * 130}\n")

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
