#!/usr/bin/env python3
"""Demo script for the generic price extractor.

Run from the backend directory:
    python -m scripts.demo_price_extraction

Or directly:
    python scripts/demo_price_extraction.py

This demo exercises all 5 extraction strategies against sample HTML pages
and shows how the confidence scoring works.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# Add backend/src to path so we can import price_radar
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from price_radar.application.price_extraction import PriceExtractor


def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_result(result: object, url: str) -> None:
    from price_radar.application.price_extraction.result import ExtractionResult

    assert isinstance(result, ExtractionResult)
    d = result.to_dict()
    status = "OK" if result.success else "FAILED"
    print(f"  URL: {url}")
    print(f"  Status: {status}")
    if result.success:
        print(f"  Current Price:  {d['current_price']} {d['currency']}")
        if d["original_price"]:
            print(f"  Original Price: {d['original_price']} {d['currency']}")
        if d["sale_price"]:
            print(f"  Sale Price:     {d['sale_price']} {d['currency']}")
        print(f"  In Stock:       {d['in_stock']}")
        print(f"  Confidence:     {d['confidence']:.0%}")
        print(f"  Strategies:     {', '.join(d['strategies_used'])}")
    print()


# ── Sample pages ────────────────────────────────────────────────────────


SAMPLE_SHOPIFY = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": "Organic Cotton Hoodie",
  "offers": {
    "@type": "Offer",
    "priceCurrency": "USD",
    "price": "64.99",
    "availability": "https://schema.org/InStock"
  }
}
</script>
<meta property="og:price:amount" content="64.99">
<meta property="og:price:currency" content="USD">
</head>
<body>
<div class="product__price">
  <span class="price-item price-item--sale">$64.99</span>
  <span class="price-item--regular price-item--last"><s>$89.99</s></span>
</div>
<span itemprop="price" content="64.99">$64.99</span>
<meta itemprop="priceCurrency" content="USD">
<button class="product-form__submit">Add to cart</button>
</body></html>
"""

SAMPLE_AMAZON = """
<html><head>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Bluetooth Speaker",
  "offers": {
    "@type": "Offer",
    "price": "49.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  }
}
</script>
</head>
<body>
<span class="a-price"><span class="a-offscreen">$49.99</span></span>
<span class="a-text-price"><span class="a-offscreen">$79.99</span></span>
<div id="availability"><span>In Stock.</span></div>
</body></html>
"""

SAMPLE_EUROPEAN = """
<html><head>
<meta property="og:price:amount" content="1499.99">
<meta property="og:price:currency" content="EUR">
<meta property="og:availability" content="instock">
</head>
<body>
<span itemprop="price" content="1499.99">1.499,99 €</span>
<meta itemprop="priceCurrency" content="EUR">
<link itemprop="availability" href="https://schema.org/InStock">
</body></html>
"""

SAMPLE_OUT_OF_STOCK = """
<html><head>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Limited Edition Sneakers",
  "offers": {
    "@type": "Offer",
    "price": "299.00",
    "priceCurrency": "USD",
    "availability": "https://schema.org/OutOfStock"
  }
}
</script>
<meta property="og:price:amount" content="299.00">
<meta property="og:availability" content="out of stock">
</head><body>
<span class="price-value">$299.00</span>
<span class="stock-status">Out of Stock</span>
</body></html>
"""

SAMPLE_SALE = """
<html><head>
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Running Shoes",
  "offers": {
    "@type": "Offer",
    "price": "89.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  }
}
</script>
<meta property="product:price:amount" content="89.99">
<meta property="product:original_price:amount" content="149.99">
<meta property="product:price:currency" content="USD">
</head>
<body>
<span itemprop="price" content="89.99">$89.99</span>
<meta itemprop="priceCurrency" content="USD">
</body></html>
"""

SAMPLE_MINIMAL = """
<html><body>
<h1>Vintage Lamp</h1>
<div class="price-box">
  <span class="sale-price">$45.00</span>
  <span class="original-price"><s>$75.00</s></span>
</div>
<button class="add-to-cart">Add to Cart</button>
</body></html>
"""

SAMPLE_GBP_AGGREGATE = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "WebPage", "name": "Tea Set"},
    {
      "@type": "Product",
      "name": "Premium Tea Set",
      "offers": {
        "@type": "AggregateOffer",
        "lowPrice": "24.95",
        "highPrice": "44.95",
        "priceCurrency": "GBP",
        "availability": "https://schema.org/InStock",
        "offerCount": 3
      }
    }
  ]
}
</script>
</head><body>
<span class="price">From £24.95</span>
</body></html>
"""

SAMPLE_CUSTOM_CSS = """
<html><body>
<div id="product-detail">
  <span class="current-price" data-price="129.99">$129.99</span>
  <span class="was-price">$179.99</span>
  <span class="stock-badge">In Stock</span>
</div>
</body></html>
"""


def main() -> None:
    print_header("Price Radar — Generic Price Extractor Demo")
    print("  Demonstrates all 5 extraction strategies with confidence scoring\n")

    # Standard extractor (no custom configs)
    extractor = PriceExtractor()

    # Custom CSS extractor
    custom_extractor = PriceExtractor(
        product_selector_config={
            "price": ".current-price",
            "original_price": ".was-price",
            "in_stock": ".stock-badge",
        }
    )

    demos = [
        ("1. Shopify Store (all strategies)", SAMPLE_SHOPIFY,
         "https://myshop.myshopify.com/products/hoodie", extractor),
        ("2. Amazon-style Page (JSON-LD + CSS)", SAMPLE_AMAZON,
         "https://www.amazon.com/dp/B0123456789", extractor),
        ("3. European Store (EUR formatting)", SAMPLE_EUROPEAN,
         "https://shop.example.de/product/laptop", extractor),
        ("4. Out of Stock Product", SAMPLE_OUT_OF_STOCK,
         "https://sneakers.example.com/limited-edition", extractor),
        ("5. Sale Price Detection", SAMPLE_SALE,
         "https://shoes.example.com/running", extractor),
        ("6. Minimal Page (regex fallback only)", SAMPLE_MINIMAL,
         "https://vintage-store.example.com/lamp", extractor),
        ("7. GBP + AggregateOffer + @graph", SAMPLE_GBP_AGGREGATE,
         "https://tea.example.co.uk/premium-set", extractor),
        ("8. Custom CSS Selectors (DB override)", SAMPLE_CUSTOM_CSS,
         "https://custom.example.com/widget", custom_extractor),
    ]

    successes = 0
    total = len(demos)

    for title, html, url, ext in demos:
        print_header(title)
        result = ext.extract(html, url)
        print_result(result, url)
        if result.success:
            successes += 1

    print_header("Summary")
    print(f"  Extracted prices from {successes}/{total} sample pages")
    pct = successes / total * 100
    print(f"  Success rate: {pct:.0f}%")
    print()

    if successes < total:
        print("  Some pages failed — this is expected for pages with no price data.")
    else:
        print("  All pages succeeded!")
    print()


if __name__ == "__main__":
    main()
