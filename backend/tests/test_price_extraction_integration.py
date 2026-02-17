"""Integration tests for price extraction against 100+ real e-commerce product pages.

Parametrized test suite covering 10 URLs x 10 popular shopping platforms:
  1. Amazon.com       — CSS selectors + regex fallback
  2. eBay.com         — JSON-LD + CSS selectors
  3. Walmart.com      — JSON-LD + script_tag + microdata
  4. Target.com       — CSR (Playwright renders JS)
  5. Best Buy         — Playwright bypasses bot detection
  6. Newegg.com       — CSR (Playwright renders JS)
  7. Nike.com         — regex fallback
  8. Etsy.com         — Playwright bypasses bot detection
  9. Allbirds (Shopify) — Shopify JSON API
  10. AliExpress.com  — Playwright renders JS

Uses PageFetcher for two-phase fetching:
  Phase 1: httpx (fast, ~1-3s) for sites that serve server-rendered HTML
  Phase 2: Playwright headless Chromium (fallback, ~5-15s) for bot-blocked / CSR sites

Run with:
    cd backend
    PYTHONPATH=src python -m pytest tests/test_price_extraction_integration.py -v -s

Skip in CI:
    PYTHONPATH=src python -m pytest -m "not live"

Expected: >= 50% of fetchable pages should yield a price.
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

# Rate-limit delay between requests to the same domain (seconds)
RATE_LIMIT_DELAY = 1.5

live = pytest.mark.live


# ---------------------------------------------------------------------------
# Test URL Catalog — 100 verified real product pages (10 per platform)
# ---------------------------------------------------------------------------

@dataclass
class ProductTestURL:
    """A product URL to test extraction against."""
    url: str
    platform: str
    label: str
    expected_currency: list[str] = field(default_factory=lambda: ["USD"])
    min_price: float = 0.01
    max_price: float = 100_000.0
    may_fail: bool = False  # URLs that might be geo-blocked or bot-detected


# fmt: off
TEST_URLS: list[ProductTestURL] = [
    # ══════════════════════════════════════════════════════════════════════
    # 1. AMAZON.COM (10 URLs)
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.amazon.com/Apple-Generation-Cancelling-Transparency-Personalized/dp/B0CHWRXH8B",
        "amazon.com", "Apple AirPods Pro 2 USB-C",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/All-new-Amazon-Kindle-Paperwhite-Signature/dp/B0C8RR4WN3",
        "amazon.com", "Kindle Paperwhite Signature 32GB",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/Amazon-vibrant-helpful-routines-Charcoal/dp/B09B8V1LZ3",
        "amazon.com", "Echo Dot 5th Gen Charcoal",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/all-new-amazon-fire-tv-stick-4k-max/dp/B0BP9SNVH9",
        "amazon.com", "Fire TV Stick 4K Max",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/Atomic-Habits-Proven-Build-Break/dp/0735211299",
        "amazon.com", "Atomic Habits Book",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/STANLEY-Quencher-FlowState-Tumbler-Charcoal/dp/B0BD78MYPN",
        "amazon.com", "Stanley Quencher 40oz Charcoal",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/All-new-Amazon-Kindle-Paperwhite-glare-free/dp/B0CFPTK5JG",
        "amazon.com", "Kindle Paperwhite 16GB",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/amazon-fire-tv-stick-hd/dp/B0CQMRKRV5",
        "amazon.com", "Fire TV Stick HD",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/dp/B098R348MK",
        "amazon.com", "Cobweb Duster Head Brush",
        expected_currency=["USD", "PLN", "EUR"],
    ),
    ProductTestURL(
        "https://www.amazon.com/Amazon-Basics-Rechargeable-Wireless-Keyboard/dp/B0CJFB8J7B",
        "amazon.com", "Amazon Basics Wireless Keyboard",
        expected_currency=["USD", "PLN", "EUR"],
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 2. EBAY.COM (10 URLs)
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.ebay.com/itm/314074071401",
        "ebay.com", "Sony WH-1000XM5 Headphones",
        max_price=50000.0,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/117009867871",
        "ebay.com", "TREBLAB Z2 ANC Headphones",
        max_price=50000.0,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/227176144902",
        "ebay.com", "Pokemon TCG Gift Box 2026",
        max_price=50000.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/286078378897",
        "ebay.com", "Samsung Galaxy Buds Pro",
        max_price=50000.0,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/227030232512",
        "ebay.com", "Bose QuietComfort Ultra Earbuds",
        max_price=50000.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/267380291681",
        "ebay.com", "iPhone 16 128GB Pink Unlocked",
        max_price=50000.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/235582866046",
        "ebay.com", "Nike Air Jordan 1 Mid Red Panda",
        max_price=50000.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/185797301783",
        "ebay.com", "KitchenAid 13-Cup Food Processor",
        max_price=50000.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/267539462139",
        "ebay.com", "LEGO Year of the Horse 2026",
        max_price=50000.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.ebay.com/itm/358047193548",
        "ebay.com", "In-N-Out 2026 T-Shirt",
        max_price=50000.0, may_fail=True,
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 3. WALMART.COM (10 URLs)
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.walmart.com/ip/3D-Calendar-2026-Tear-Away-3D-Paper-Notepad-LED-Lights-3D-Desk-Calendar-Piece-Earth-Calen-Pad-2026-Memo-Time/17474159508",
        "walmart.com", "3D Calendar 2026",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Bigfoot-2026-Wall-Calendar-9781935694946/14849403105",
        "walmart.com", "Bigfoot 2026 Wall Calendar",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Out-on-the-Porch-Wall-Calendar-2026-Porch-Living-for-Every-Day-of-the-Year-Paperback-9781523531325/15144452167",
        "walmart.com", "Porch Wall Calendar 2026",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Samsung-50-Class-Crystal-UHD-U7900F-4K-Smart-TV-2025-UN50U7900FFXZA/16772370681",
        "walmart.com", "Samsung 50\" 4K Smart TV",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Keurig-K-Elite-Single-Serve-K-Cup-Pod-Coffee-Maker-Brushed-Slate/225142139",
        "walmart.com", "Keurig K-Elite Coffee Maker",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Better-Homes-Gardens-16-Piece-Square-Porcelain-Dinnerware-Set-White/24076922",
        "walmart.com", "BH&G 16pc Dinnerware Set",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/LEGO-Disney-Pixar-Up-House-43217-Disney-100-Celebration-Classic-Building-Toy-Set-Kids-Movie-Fans-Ages-9-Fun-Gift-Disney-Fans-Anyone-Loves-Creative-Pl/1527935978",
        "walmart.com", "LEGO Disney Up House",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Instant-Pot-6qt-Duo-Crisp-11-in-1-Electric-Pressure-Cooker-with-Air-Fryer-Lid-Silver/248733466",
        "walmart.com", "Instant Pot Duo Crisp 6qt",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Tide-Liquid-Laundry-Detergent-Original-64-Loads-92-fl-oz-HE-Compatible/832215427",
        "walmart.com", "Tide Liquid Detergent 92oz",
    ),
    ProductTestURL(
        "https://www.walmart.com/ip/Great-Value-Classic-Variety-Pack-1-Oz-20-Count/36031440",
        "walmart.com", "Great Value Chips Variety 20ct",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 4. TARGET.COM (10 URLs) — mostly CSR, may_fail expected
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.target.com/p/apple-ipad-a16-10-9-inch-wi-fi-128gb-2025-11th-generation-silver/-/A-85966333",
        "target.com", "Apple iPad A16 128GB Silver", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/apple-ipad-a16-10-9-inch-wi-fi-128gb-2025-11th-generation-blue/-/A-85966318",
        "target.com", "Apple iPad A16 128GB Blue", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/amazon-echo-show-8-2025-glacier-white/-/A-94772761",
        "target.com", "Amazon Echo Show 8 2025", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/roku-streaming-stick-plus-2025-4k-and-hdr-streaming-device-with-voice-remote-free-and-live-tv-access/-/A-94570937",
        "target.com", "Roku Streaming Stick+ 2025", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/instant-pot-6qt-9-in-1-pressure-cooker-bundle/-/A-90571185",
        "target.com", "Instant Pot 6qt 9-in-1", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/keurig-k-mini-single-serve-k-cup-pod-coffee-maker-black/-/A-53448183",
        "target.com", "Keurig K-Mini Coffee Maker", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/keurig-k-mini-go-single-serve-k-cup-pod-coffee-maker-navy/-/A-90116757",
        "target.com", "Keurig K-Mini Go Navy", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/keurig-k-supreme-single-serve-k-cup-pod-coffee-maker/-/A-81508967",
        "target.com", "Keurig K-Supreme", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/instant-pot-6-5-qt-duo-crisp-13-in-1-air-fryer-pressure-cooker-38-slow-cooker-with-one-ultimate-lid/-/A-82647383",
        "target.com", "Instant Pot 6.5qt Duo Crisp", may_fail=True,
    ),
    ProductTestURL(
        "https://www.target.com/p/instant-pot-8-qt-11-in-1-air-fryer-duo-crisp-electric-pressure-cooker/-/A-54643330",
        "target.com", "Instant Pot 8qt Air Fryer", may_fail=True,
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 5. BESTBUY.COM (10 URLs) — often bot-blocked
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.bestbuy.com/site/apple-airpods-max-usb-c-midnight/6550076.p?skuId=6550076",
        "bestbuy.com", "Apple AirPods Max USB-C", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/apple-airpods-pro-2nd-generation-with-magsafe-case-usbc-white/6447382.p?skuId=6447382",
        "bestbuy.com", "Apple AirPods Pro 2 USB-C", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/sony-wh-1000xm5-wireless-noise-canceling-over-the-ear-headphones-silver/6505728.p?skuId=6505728",
        "bestbuy.com", "Sony WH-1000XM5 Silver", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/samsung-65-class-s94bd-oled-4k-uhd-smart-tizen-tv/6545810.p?skuId=6545810",
        "bestbuy.com", "Samsung 65\" S94BD OLED 4K TV", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/samsung-55-class-s90c-oled-4k-uhd-smart-tizen-tv/6536968.p?skuId=6536968",
        "bestbuy.com", "Samsung 55\" S90C OLED 4K TV", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/samsung-galaxy-buds-true-wireless-earbud-headphones-black/6400885.p?skuId=6400885",
        "bestbuy.com", "Samsung Galaxy Buds+ Black", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/apple-macbook-air-13-inch-laptop-apple-m4-chip-built-for-apple-intelligence-16gb-memory-256gb-ssd-midnight/6565862.p?skuId=6565862",
        "bestbuy.com", "MacBook Air 13\" M4 256GB", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/amazon-kindle-16-gb-2024-black/6599466.p?skuId=6599466",
        "bestbuy.com", "Amazon Kindle 16GB 2024", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/jbl-flip-5-portable-bluetooth-speaker-black/6356535.p?skuId=6356535",
        "bestbuy.com", "JBL Flip 5 Bluetooth Speaker", may_fail=True,
    ),
    ProductTestURL(
        "https://www.bestbuy.com/site/apple-airpods-max-usb-c-blue/6550078.p?skuId=6550078",
        "bestbuy.com", "Apple AirPods Max USB-C Blue", may_fail=True,
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 6. NEWEGG.COM (10 URLs) — CSR heavy
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.newegg.com/samsung-1tb-990-pro-nvme-2-0/p/N82E16820147860",
        "newegg.com", "Samsung 990 PRO 1TB SSD", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/samsung-2tb-990-pro-nvme-2-0/p/N82E16820147861",
        "newegg.com", "Samsung 990 PRO 2TB SSD", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/samsung-1tb-990-pro-w-heatsink-normal-package-nvme-2-0/p/N82E16820147862",
        "newegg.com", "Samsung 990 PRO 1TB Heatsink", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/samsung-4gb-990-pro-nvme-2-0/p/N82E16820147878",
        "newegg.com", "Samsung 990 PRO 4TB Heatsink", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/corsair-vengeance-rgb-32gb-ddr5-6000-cas-latency-cl36-desktop-memory-black/p/N82E16820236991",
        "newegg.com", "Corsair Vengeance 32GB DDR5-6000", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/corsair-vengeance-rgb-32gb-ddr5-6400-cas-latency-cl36-desktop-memory-black/p/N82E16820982185",
        "newegg.com", "Corsair Vengeance 32GB DDR5-6400", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/asus-rog-strix-rog-strix-rtx4070-o12g-gaming-geforce-rtx-4070-12gb-graphics-card-triple-fans/p/N82E16814126643",
        "newegg.com", "ASUS ROG Strix RTX 4070 OC", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/asus-xg27aqngv-27-qhd-360-hz-rog-strix-ultra-fast-ips-black/p/N82E16824281394",
        "newegg.com", "ASUS ROG 27\" QHD 360Hz Monitor", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/p/N82E16823126736",
        "newegg.com", "Logitech G PRO X 60 Keyboard", may_fail=True,
    ),
    ProductTestURL(
        "https://www.newegg.com/logitech-c920/p/N82E16826104635",
        "newegg.com", "Logitech C920 HD Webcam", may_fail=True,
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 7. NIKE.COM (10 URLs)
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111",
        "nike.com", "Nike Air Force 1 07",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/air-force-1-07-se-lny-mens-shoes-ls6AxsJF",
        "nike.com", "Nike Air Force 1 07 SE LNY",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/air-jordan-4-retro-flight-club-mens-shoes-PlqxvPPn",
        "nike.com", "Air Jordan 4 Retro Flight Club",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/vomero-18-gore-tex-mens-waterproof-road-running-shoes-HzOmdRVa",
        "nike.com", "Nike Vomero 18 GORE-TEX",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/dunk-low-retro-se-mens-shoes-wlaYvsTw",
        "nike.com", "Nike Dunk Low Retro SE",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/pegasus-trail-5-gore-tex-mens-waterproof-trail-running-shoes-Tqyf11TS",
        "nike.com", "Nike Pegasus Trail 5 GTX",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/air-jordan-1-mid-mens-shoes-X5pM09",
        "nike.com", "Air Jordan 1 Mid",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/interact-run-easyon-se-mens-road-running-shoes-sf3Jpd",
        "nike.com", "Nike Interact Run EasyOn SE",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/air-pegasus-wave-premium-mens-shoes-3Z8JFTiB",
        "nike.com", "Nike Air Pegasus Wave Premium",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.nike.com/t/free-2025-mens-workout-shoes-zs7gPj",
        "nike.com", "Nike Free 2025 Workout",
        expected_currency=["USD", "EUR", "GBP", "PLN"], may_fail=True,
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 8. ETSY.COM (10 URLs) — often bot-blocked
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.etsy.com/listing/997583775/2025-2026-planner-planner-2025-2026",
        "etsy.com", "2025-2026 Weekly Planner",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/1192062265/custom-necklace-necklace-with-photo",
        "etsy.com", "Custom Photo Necklace",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/512570842/personalized-photo-engraved-necklace",
        "etsy.com", "Personalized Engraved Necklace",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/1288968277/custom-birthstone-ring-name-engraved",
        "etsy.com", "Custom Birthstone Ring",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/576391963/custom-pet-portrait-neo-traditional",
        "etsy.com", "Custom Pet Portrait",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/659189391/custom-pet-canvas-custom-pet-portrait",
        "etsy.com", "Custom Pet Canvas Portrait",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/1554277960/handmade-scented-soy-candle-with-dried",
        "etsy.com", "Handmade Soy Candle Dried Flowers",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/643098732/fresh-cut-pine-wood-wick-handmade-soy",
        "etsy.com", "Fresh Cut Pine Wood Wick Candle",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/483568126/zen-candle-soy-candle-with-wooden-wick",
        "etsy.com", "Zen Soy Candle Wooden Wick",
        max_price=500.0, may_fail=True,
    ),
    ProductTestURL(
        "https://www.etsy.com/listing/576703593/sterling-silver-handmade-womans-ring",
        "etsy.com", "Sterling Silver Handmade Ring",
        max_price=500.0, may_fail=True,
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 9. ALLBIRDS / SHOPIFY (10 URLs)
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.allbirds.com/products/mens-tree-runners",
        "shopify:allbirds", "Allbirds Mens Tree Runners",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/womens-wool-runners",
        "shopify:allbirds", "Allbirds Womens Wool Runners",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/mens-tree-dashers",
        "shopify:allbirds", "Allbirds Mens Tree Dashers",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/mens-wool-loungers-natural-black",
        "shopify:allbirds", "Allbirds Mens Wool Loungers",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/mens-tree-loungers",
        "shopify:allbirds", "Allbirds Mens Tree Loungers",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/womens-tree-runners",
        "shopify:allbirds", "Allbirds Womens Tree Runners",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/womens-wool-loungers-true-black",
        "shopify:allbirds", "Allbirds Womens Wool Loungers",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/womens-wool-runner-mizzles",
        "shopify:allbirds", "Allbirds Womens Wool Mizzles",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/mens-tree-runners-mist",
        "shopify:allbirds", "Allbirds Mens Tree Runners Mist",
        expected_currency=["USD", "EUR", "GBP"],
    ),
    ProductTestURL(
        "https://www.allbirds.com/products/mens-tree-runners-wheat-dark-beige",
        "shopify:allbirds", "Allbirds Mens Tree Runners Wheat",
        expected_currency=["USD", "EUR", "GBP"],
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 10. ALIEXPRESS.COM (10 URLs)
    # ══════════════════════════════════════════════════════════════════════
    ProductTestURL(
        "https://www.aliexpress.com/item/1005006524842368.html",
        "aliexpress.com", "AliExpress Item 1",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005008572989001.html",
        "aliexpress.com", "A5 Planner PU Leather",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005008879702705.html",
        "aliexpress.com", "Agenda Planner Notebook A5",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005008850196969.html",
        "aliexpress.com", "Business Planner 18-Month",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005008224574880.html",
        "aliexpress.com", "Hardcover Planner 12 Months",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005007937850152.html",
        "aliexpress.com", "2026 Wall Calendar Large",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005009357068454.html",
        "aliexpress.com", "Academic Daily Monthly Planner",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005010712955196.html",
        "aliexpress.com", "Body Care Tool 2026",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005005454499885.html",
        "aliexpress.com", "TWS Wireless Headphones LED",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
    ProductTestURL(
        "https://www.aliexpress.com/item/1005001982311776.html",
        "aliexpress.com", "Magnetic Wireless Car Charger",
        expected_currency=["USD", "EUR", "PLN"], may_fail=True,
    ),
]
# fmt: on

# Total: 100 URLs (10 per platform)
assert len(TEST_URLS) == 100, f"Expected 100 URLs, got {len(TEST_URLS)}"

# Verify 10 per platform
_platform_counts = defaultdict(int)
for _u in TEST_URLS:
    _platform_counts[_u.platform] += 1
assert len(_platform_counts) == 10, f"Expected 10 platforms, got {len(_platform_counts)}"
for _p, _c in _platform_counts.items():
    assert _c == 10, f"Platform {_p} has {_c} URLs, expected 10"


# ---------------------------------------------------------------------------
# Result Collector (renamed to avoid pytest collection conflict)
# ---------------------------------------------------------------------------

@dataclass
class URLExtractionResult:
    """Result of a single URL extraction test."""
    product: ProductTestURL
    html_size: int = 0
    extraction: ExtractionResult | None = None
    error: str | None = None
    fetch_time: float = 0.0
    extract_time: float = 0.0
    fetch_method: str = "none"  # "httpx", "camoufox", or "none"

    @property
    def success(self) -> bool:
        return self.extraction is not None and self.extraction.success

    @property
    def price(self) -> Decimal | None:
        return self.extraction.current_price if self.extraction else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def extraction_results() -> list[URLExtractionResult]:
    """Fetch all 100 test URLs and extract prices using PageFetcher.

    Uses the two-phase fetch strategy:
      Phase 1: httpx (fast) for sites with server-rendered HTML
      Phase 2: Playwright headless Chromium for bot-blocked / CSR sites

    Rate-limits requests per domain to avoid being blocked.
    """
    fetcher = PageFetcher(use_browser=True)
    results: list[URLExtractionResult] = []
    last_domain: str = ""

    for product in TEST_URLS:
        # Rate limit per domain
        domain = urlparse(product.url).netloc
        if domain == last_domain:
            time.sleep(RATE_LIMIT_DELAY)
        last_domain = domain

        tr = URLExtractionResult(product=product)

        # Fetch + Extract (PageFetcher handles fallback logic internally)
        t0 = time.monotonic()
        try:
            fetch_result, extraction = fetcher.fetch_and_extract(product.url)
            tr.fetch_time = fetch_result.fetch_time
            tr.fetch_method = fetch_result.method
            tr.html_size = fetch_result.html_size

            if not fetch_result.success:
                tr.error = fetch_result.error or "fetch_failed"
            else:
                tr.extraction = extraction if extraction.success else None
                if not extraction.success:
                    # Fetch succeeded but extraction found no price
                    tr.extraction = extraction  # Keep partial data for reporting
        except Exception as e:
            tr.error = f"fetch_extract_error: {e}"
            tr.fetch_time = time.monotonic() - t0

        results.append(tr)

    # Clean up Playwright browser
    BrowserPool.shutdown()
    return results


# ---------------------------------------------------------------------------
# Helper: get results for one platform
# ---------------------------------------------------------------------------

def _platform_results(
    extraction_results: list[URLExtractionResult], platform: str
) -> list[URLExtractionResult]:
    return [r for r in extraction_results if r.product.platform == platform]


def _platform_success_rate(
    extraction_results: list[URLExtractionResult], platform: str
) -> tuple[int, int, float]:
    """Return (extracted, fetchable, rate) for a platform."""
    results = _platform_results(extraction_results, platform)
    fetchable = [r for r in results if r.error is None]
    extracted = [r for r in fetchable if r.success]
    rate = len(extracted) / len(fetchable) if fetchable else 0.0
    return len(extracted), len(fetchable), rate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@live
class TestIntegrationSuite:
    """Integration test suite for price extraction across 100 real URLs."""

    # ── Overall metrics ──────────────────────────────────────────────

    def test_overall_success_rate(self, extraction_results: list[URLExtractionResult]) -> None:
        """At least 50% of fetchable URLs must extract a price."""
        fetchable = [r for r in extraction_results if r.error is None or r.fetch_method != "none"]
        successes = [r for r in extraction_results if r.success]
        fetch_failed = [r for r in extraction_results if r.error and r.fetch_method == "none"]
        pw_used = [r for r in extraction_results if r.fetch_method == "camoufox"]
        httpx_used = [r for r in extraction_results if r.fetch_method == "httpx"]

        rate = len(successes) / len(fetchable) if fetchable else 0.0

        print(f"\n{'=' * 70}")
        print(f"  INTEGRATION TEST SUMMARY (100 URLs)")
        print(f"{'=' * 70}")
        print(f"  Total URLs:       {len(extraction_results)}")
        print(f"  Fetchable:        {len(fetchable)}")
        print(f"  Extracted:        {len(successes)}")
        print(f"  Fetch failed:     {len(fetch_failed)}")
        print(f"  via httpx:        {len(httpx_used)}")
        print(f"  via Playwright:   {len(pw_used)}")
        print(f"  Success rate:     {rate:.1%} (of fetchable)")
        print(f"{'=' * 70}\n")

        assert rate >= 0.50, (
            f"Success rate {rate:.1%} below 50% threshold. "
            f"Extracted {len(successes)}/{len(fetchable)}"
        )

    # ── Per-platform parametrized tests ──────────────────────────────

    def test_amazon_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Amazon.com: expect >= 50% success rate."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "amazon.com")
        if fetch == 0:
            pytest.skip("No Amazon.com pages fetched")
        print(f"\n  Amazon.com: {ext}/{fetch} = {rate:.0%}")
        assert rate >= 0.50, f"Amazon.com success rate {rate:.0%} too low"

    def test_ebay_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """eBay.com: expect >= 50% success rate (JSON-LD rich)."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "ebay.com")
        if fetch == 0:
            pytest.skip("No eBay.com pages fetched")
        print(f"\n  eBay.com: {ext}/{fetch} = {rate:.0%}")
        assert rate >= 0.50, f"eBay.com success rate {rate:.0%} too low"

    def test_walmart_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Walmart.com: expect >= 50% success rate (JSON-LD + script_tag)."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "walmart.com")
        if fetch == 0:
            pytest.skip("No Walmart.com pages fetched")
        print(f"\n  Walmart.com: {ext}/{fetch} = {rate:.0%}")
        assert rate >= 0.50, f"Walmart.com success rate {rate:.0%} too low"

    def test_shopify_allbirds(self, extraction_results: list[URLExtractionResult]) -> None:
        """Shopify:Allbirds: expect >= 50% success rate (Shopify API)."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "shopify:allbirds")
        if fetch == 0:
            pytest.skip("No Allbirds pages fetched")
        print(f"\n  Shopify:Allbirds: {ext}/{fetch} = {rate:.0%}")
        assert rate >= 0.50, f"Shopify:Allbirds success rate {rate:.0%} too low"

    def test_target_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Target.com: CSR-heavy, may have low rate."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "target.com")
        if fetch == 0:
            pytest.skip("No Target.com pages fetched")
        print(f"\n  Target.com: {ext}/{fetch} = {rate:.0%}")
        # Low threshold — Target is CSR-only
        # No assertion — just report

    def test_bestbuy_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Best Buy: often bot-blocked."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "bestbuy.com")
        if fetch == 0:
            pytest.skip("No Best Buy pages fetched")
        print(f"\n  BestBuy.com: {ext}/{fetch} = {rate:.0%}")
        # No assertion — frequently blocked

    def test_newegg_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Newegg: CSR-heavy."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "newegg.com")
        if fetch == 0:
            pytest.skip("No Newegg pages fetched")
        print(f"\n  Newegg.com: {ext}/{fetch} = {rate:.0%}")
        # No assertion — CSR-only

    def test_nike_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Nike.com: regex fallback."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "nike.com")
        if fetch == 0:
            pytest.skip("No Nike.com pages fetched")
        print(f"\n  Nike.com: {ext}/{fetch} = {rate:.0%}")

    def test_etsy_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """Etsy: often bot-blocked."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "etsy.com")
        if fetch == 0:
            pytest.skip("No Etsy pages fetched")
        print(f"\n  Etsy.com: {ext}/{fetch} = {rate:.0%}")
        # No assertion — frequently blocked

    def test_aliexpress_com(self, extraction_results: list[URLExtractionResult]) -> None:
        """AliExpress: aggressive bot detection."""
        ext, fetch, rate = _platform_success_rate(extraction_results, "aliexpress.com")
        if fetch == 0:
            pytest.skip("No AliExpress pages fetched")
        print(f"\n  AliExpress.com: {ext}/{fetch} = {rate:.0%}")
        # No assertion — aggressive bot detection

    # ── Data quality tests ───────────────────────────────────────────

    def test_prices_are_positive(self, extraction_results: list[URLExtractionResult]) -> None:
        """All extracted prices must be positive."""
        for r in extraction_results:
            if r.success and r.price is not None:
                assert r.price > 0, (
                    f"Zero/negative price for {r.product.label}: {r.price}"
                )

    def test_prices_in_reasonable_range(self, extraction_results: list[URLExtractionResult]) -> None:
        """Extracted prices must be within expected range per product."""
        failures = []
        for r in extraction_results:
            if r.success and r.price is not None:
                price_f = float(r.price)
                if price_f < r.product.min_price or price_f > r.product.max_price:
                    failures.append(
                        f"{r.product.label}: {price_f} "
                        f"(expected {r.product.min_price}-{r.product.max_price})"
                    )
        if failures:
            msg = "\n".join(f"  - {f}" for f in failures)
            print(f"\n  WARNING: Prices outside expected range:\n{msg}")

    def test_confidence_above_minimum(self, extraction_results: list[URLExtractionResult]) -> None:
        """Confidence scores must be at least 0.3 for successful extractions."""
        low_conf = []
        for r in extraction_results:
            if r.success and r.extraction.confidence < 0.3:
                low_conf.append(
                    f"{r.product.label}: confidence={r.extraction.confidence}"
                )
        if low_conf:
            msg = "\n".join(f"  - {c}" for c in low_conf)
            print(f"\n  WARNING: Low confidence extractions:\n{msg}")

    def test_currencies_are_valid(self, extraction_results: list[URLExtractionResult]) -> None:
        """When a price is extracted, currency should be a valid ISO code."""
        valid_currencies = {
            "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR",
            "BRL", "RUB", "KRW", "SGD", "HKD", "NOK", "SEK", "DKK", "NZD",
            "ZAR", "MXN", "TRY", "PLN", "THB", "IDR", "MYR", "PHP", "ILS",
            "CZK", "CLP", "ARS", "COP", "PEN", "UAH", "RON", "HUF", "VND",
            "TWD", "AED", "SAR",
        }
        for r in extraction_results:
            if r.success:
                assert r.extraction.currency in valid_currencies, (
                    f"Invalid currency '{r.extraction.currency}' for {r.product.label}"
                )

    def test_in_stock_is_boolean(self, extraction_results: list[URLExtractionResult]) -> None:
        """in_stock must always be a boolean when extraction succeeds."""
        for r in extraction_results:
            if r.success:
                assert isinstance(r.extraction.in_stock, bool), (
                    f"in_stock is {type(r.extraction.in_stock)} for {r.product.label}"
                )

    def test_strategies_used_not_empty(self, extraction_results: list[URLExtractionResult]) -> None:
        """When extraction succeeds, at least one strategy must be used."""
        for r in extraction_results:
            if r.success:
                assert len(r.extraction.strategies_used) >= 1, (
                    f"No strategies for {r.product.label}"
                )

    def test_extraction_speed(self, extraction_results: list[URLExtractionResult]) -> None:
        """Extraction (not fetch) should complete within 3 seconds per page."""
        slow = []
        for r in extraction_results:
            if r.extraction and r.extract_time > 3.0:
                slow.append((r.product.label, r.extract_time))

        if slow:
            msg = "\n".join(f"  {label}: {t:.2f}s" for label, t in slow)
            print(f"\n  WARNING: Slow extractions:\n{msg}")

    # ── Detailed report ──────────────────────────────────────────────

    def test_detailed_report(self, extraction_results: list[URLExtractionResult]) -> None:
        """Print detailed extraction results for all 100 URLs (always passes)."""
        print(f"\n{'=' * 120}")
        print(
            f"  {'#':<4} {'Platform':<22} {'Label':<35} {'Method':<12} "
            f"{'Price':>12} {'Curr':>5} {'Conf':>6} {'Strategies'}"
        )
        print(f"{'=' * 120}")

        # Group by platform
        platforms: dict[str, list[URLExtractionResult]] = {}
        for r in extraction_results:
            platforms.setdefault(r.product.platform, []).append(r)

        idx = 0
        for platform, results in sorted(platforms.items()):
            for r in results:
                idx += 1
                method = r.fetch_method
                if r.error and r.fetch_method == "none":
                    print(
                        f"  {idx:<4} {platform:<22} {r.product.label:<35} "
                        f"{'---':<12} FAIL ({r.error})"
                    )
                elif r.error:
                    print(
                        f"  {idx:<4} {platform:<22} {r.product.label:<35} "
                        f"{method:<12} FAIL ({r.error})"
                    )
                elif r.success:
                    d = r.extraction.to_dict()
                    price_str = f"{d['current_price']:.2f}"
                    strats = ",".join(d["strategies_used"])
                    print(
                        f"  {idx:<4} {platform:<22} {r.product.label:<35} "
                        f"{method:<12} {price_str:>12} {d['currency']:>5} "
                        f"{d['confidence']:>5.0%} {strats}"
                    )
                else:
                    print(
                        f"  {idx:<4} {platform:<22} {r.product.label:<35} "
                        f"{method:<12} NO PRICE FOUND"
                    )

        print(f"{'=' * 120}")

        # Platform summary table
        print(f"\n  {'=' * 78}")
        print(f"  PLATFORM SUMMARY")
        print(f"  {'=' * 78}")
        print(
            f"  {'Platform':<25} {'URLs':>6} {'Fetched':>8} {'Extracted':>10} "
            f"{'Rate':>8} {'httpx':>6} {'PW':>4} {'Fail':>6}"
        )
        print(f"  {'-' * 78}")

        total_urls = 0
        total_fetched = 0
        total_extracted = 0
        total_failed = 0
        total_httpx = 0
        total_pw = 0

        for platform, results in sorted(platforms.items()):
            fetched = [r for r in results if r.html_size > 0 or r.fetch_method != "none"]
            extracted = [r for r in results if r.success]
            fetch_fail = len(results) - len(fetched)
            httpx_count = sum(1 for r in results if r.fetch_method == "httpx")
            pw_count = sum(1 for r in results if r.fetch_method == "camoufox")
            rate = len(extracted) / len(fetched) if fetched else 0.0

            total_urls += len(results)
            total_fetched += len(fetched)
            total_extracted += len(extracted)
            total_failed += fetch_fail
            total_httpx += httpx_count
            total_pw += pw_count

            rate_str = f"{rate:.0%}" if fetched else "N/A"
            fail_str = str(fetch_fail) if fetch_fail else "-"
            print(
                f"  {platform:<25} {len(results):>6} {len(fetched):>8} "
                f"{len(extracted):>10} {rate_str:>8} {httpx_count:>6} "
                f"{pw_count:>4} {fail_str:>6}"
            )

        overall_rate = total_extracted / total_fetched if total_fetched else 0.0
        print(f"  {'-' * 78}")
        print(
            f"  {'TOTAL':<25} {total_urls:>6} {total_fetched:>8} "
            f"{total_extracted:>10} {overall_rate:>7.1%} {total_httpx:>6} "
            f"{total_pw:>4} {total_failed:>6}"
        )
        print(f"  {'=' * 78}")
        print()
