"""Comprehensive tests for the generic price extraction module."""

from decimal import Decimal

import pytest

from price_radar.application.price_extraction.extractor import PriceExtractor
from price_radar.application.price_extraction.normalizer import (
    detect_currency,
    normalize_currency_code,
    parse_price,
)
from price_radar.application.price_extraction.result import ExtractionResult, PriceData
from price_radar.application.price_extraction.strategies.css_selector import CSSSelectorStrategy
from price_radar.application.price_extraction.strategies.json_ld import JsonLdStrategy
from price_radar.application.price_extraction.strategies.microdata import MicrodataStrategy
from price_radar.application.price_extraction.strategies.open_graph import OpenGraphStrategy
from price_radar.application.price_extraction.strategies.regex_fallback import (
    RegexFallbackStrategy,
)
from price_radar.application.price_extraction.strategies.script_tag import ScriptTagStrategy
from price_radar.application.price_extraction.strategies.shopify_api import ShopifyApiStrategy


# ─── Helpers ────────────────────────────────────────────────────────────

def _make_soup(html: str) -> "BeautifulSoup":
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


# ─── Price normalization tests ──────────────────────────────────────────


class TestParsePrice:
    """Tests for parse_price()."""

    def test_simple_usd(self) -> None:
        assert parse_price("$29.99") == Decimal("29.99")

    def test_simple_int(self) -> None:
        assert parse_price("100") == Decimal("100")

    def test_thousands_comma(self) -> None:
        assert parse_price("$1,234.56") == Decimal("1234.56")

    def test_european_format(self) -> None:
        assert parse_price("1.234,56 €") == Decimal("1234.56")

    def test_european_simple(self) -> None:
        assert parse_price("12,50") == Decimal("12.50")

    def test_thousands_only(self) -> None:
        assert parse_price("1,234") == Decimal("1234")

    def test_multiple_thousands(self) -> None:
        assert parse_price("$1,234,567.89") == Decimal("1234567.89")

    def test_euro_symbol(self) -> None:
        assert parse_price("€99.99") == Decimal("99.99")

    def test_pound_symbol(self) -> None:
        assert parse_price("£49.95") == Decimal("49.95")

    def test_yen_no_decimal(self) -> None:
        assert parse_price("¥1234") == Decimal("1234")

    def test_with_currency_code(self) -> None:
        assert parse_price("USD 29.99") == Decimal("29.99")

    def test_whitespace(self) -> None:
        assert parse_price("  $  42.00  ") == Decimal("42.00")

    def test_empty_string(self) -> None:
        assert parse_price("") is None

    def test_no_digits(self) -> None:
        assert parse_price("abc") is None

    def test_negative_returns_none(self) -> None:
        assert parse_price("-$10.00") is None

    def test_multiple_dots_thousands(self) -> None:
        assert parse_price("1.234.567") == Decimal("1234567")


class TestDetectCurrency:
    """Tests for detect_currency()."""

    def test_dollar_sign(self) -> None:
        assert detect_currency("$29.99") == "USD"

    def test_euro_sign(self) -> None:
        assert detect_currency("€99.99") == "EUR"

    def test_pound_sign(self) -> None:
        assert detect_currency("£49.95") == "GBP"

    def test_yen_sign(self) -> None:
        assert detect_currency("¥1234") == "JPY"

    def test_iso_code(self) -> None:
        assert detect_currency("29.99 CAD") == "CAD"

    def test_brl_symbol(self) -> None:
        assert detect_currency("R$99.90") == "BRL"

    def test_no_currency(self) -> None:
        assert detect_currency("29.99") is None


class TestNormalizeCurrencyCode:
    """Tests for normalize_currency_code()."""

    def test_valid_code(self) -> None:
        assert normalize_currency_code("EUR") == "EUR"

    def test_none_defaults_usd(self) -> None:
        assert normalize_currency_code(None) == "USD"

    def test_symbol_conversion(self) -> None:
        assert normalize_currency_code("€") == "EUR"


# ─── Strategy 1: JSON-LD ───────────────────────────────────────────────


class TestJsonLdStrategy:
    """Tests for JSON-LD structured data extraction."""

    strategy = JsonLdStrategy()

    def test_standard_product(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Test Product",
          "offers": {
            "@type": "Offer",
            "price": "29.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        </head><body></body></html>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com/product")
        assert result is not None
        assert result.current_price == Decimal("29.99")
        assert result.currency == "USD"
        assert result.in_stock is True

    def test_aggregate_offer(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "offers": {
            "@type": "AggregateOffer",
            "lowPrice": "19.99",
            "highPrice": "49.99",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("19.99")
        assert result.currency == "EUR"

    def test_graph_wrapper(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "WebPage"},
            {
              "@type": "Product",
              "offers": {
                "@type": "Offer",
                "price": "149.00",
                "priceCurrency": "GBP"
              }
            }
          ]
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.co.uk")
        assert result is not None
        assert result.current_price == Decimal("149.00")
        assert result.currency == "GBP"

    def test_out_of_stock(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "50.00", "priceCurrency": "USD",
          "availability": "https://schema.org/OutOfStock"
        }}
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is False

    def test_offers_list(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": [
          {"@type": "Offer", "price": "25.00", "priceCurrency": "USD"},
          {"@type": "Offer", "price": "30.00", "priceCurrency": "USD"}
        ]}
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("25.00")

    def test_no_json_ld(self) -> None:
        html = "<html><body>No structured data</body></html>"
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_invalid_json(self) -> None:
        html = '<script type="application/ld+json">{ invalid json }</script>'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_non_product_type(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type": "Organization", "name": "Acme Corp"}
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_price_specification(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer",
          "priceSpecification": {
            "price": "39.99",
            "priceCurrency": "CAD"
          }
        }}
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.ca")
        assert result is not None
        assert result.current_price == Decimal("39.99")
        assert result.currency == "CAD"

    def test_list_type(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type": ["Product", "Thing"], "offers": {
          "@type": "Offer", "price": "15.00", "priceCurrency": "USD"
        }}
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("15.00")


# ─── Strategy 2: Open Graph ────────────────────────────────────────────


class TestOpenGraphStrategy:
    """Tests for Open Graph meta tag extraction."""

    strategy = OpenGraphStrategy()

    def test_og_price(self) -> None:
        html = """
        <html><head>
        <meta property="og:price:amount" content="49.99">
        <meta property="og:price:currency" content="USD">
        </head><body></body></html>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("49.99")
        assert result.currency == "USD"

    def test_product_price(self) -> None:
        html = """
        <meta property="product:price:amount" content="79.95">
        <meta property="product:price:currency" content="EUR">
        """
        result = self.strategy.extract(_make_soup(html), "https://example.eu")
        assert result is not None
        assert result.current_price == Decimal("79.95")
        assert result.currency == "EUR"

    def test_availability_in_stock(self) -> None:
        html = """
        <meta property="og:price:amount" content="10.00">
        <meta property="og:availability" content="instock">
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is True

    def test_availability_out_of_stock(self) -> None:
        html = """
        <meta property="og:price:amount" content="10.00">
        <meta property="og:availability" content="out of stock">
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is False

    def test_no_og_tags(self) -> None:
        html = '<meta property="og:title" content="Page">'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_sale_price(self) -> None:
        html = """
        <meta property="product:price:amount" content="29.99">
        <meta property="product:sale_price:amount" content="19.99">
        <meta property="product:price:currency" content="USD">
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("29.99")
        assert result.sale_price == Decimal("19.99")

    def test_name_attr_fallback(self) -> None:
        html = '<meta name="price" content="99.99">'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("99.99")


# ─── Strategy 3: Microdata ─────────────────────────────────────────────


class TestMicrodataStrategy:
    """Tests for HTML5 microdata extraction."""

    strategy = MicrodataStrategy()

    def test_itemprop_content(self) -> None:
        html = """
        <div itemscope itemtype="https://schema.org/Product">
          <meta itemprop="price" content="59.99">
          <meta itemprop="priceCurrency" content="USD">
        </div>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("59.99")
        assert result.currency == "USD"

    def test_itemprop_text(self) -> None:
        html = '<span itemprop="price">$29.99</span>'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("29.99")

    def test_availability_href(self) -> None:
        html = """
        <span itemprop="price" content="40.00">$40.00</span>
        <link itemprop="availability" href="https://schema.org/InStock">
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is True

    def test_out_of_stock(self) -> None:
        html = """
        <span itemprop="price" content="40.00">$40.00</span>
        <link itemprop="availability" href="https://schema.org/OutOfStock">
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is False

    def test_no_microdata(self) -> None:
        html = "<span>Just a price: $10.00</span>"
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None


# ─── Strategy 4: CSS Selectors ──────────────────────────────────────────


class TestCSSSelectorStrategy:
    """Tests for CSS selector extraction."""

    def test_product_config_override(self) -> None:
        html = '<span class="my-price">$99.99</span>'
        strategy = CSSSelectorStrategy(product_config={"price": ".my-price"})
        result = strategy.extract(_make_soup(html), "https://custom-store.com/product")
        assert result is not None
        assert result.current_price == Decimal("99.99")

    def test_db_config(self) -> None:
        html = '<span id="sale-price">€49.50</span>'
        strategy = CSSSelectorStrategy(
            db_configs={"mystore.com": {"price": "#sale-price"}}
        )
        result = strategy.extract(_make_soup(html), "https://www.mystore.com/p/123")
        assert result is not None
        assert result.current_price == Decimal("49.50")
        assert result.currency == "EUR"

    def test_builtin_amazon_selectors(self) -> None:
        html = """
        <span class="a-price">
          <span class="a-offscreen">$149.99</span>
        </span>
        """
        strategy = CSSSelectorStrategy()
        result = strategy.extract(_make_soup(html), "https://www.amazon.com/dp/B123")
        assert result is not None
        assert result.current_price == Decimal("149.99")

    def test_original_price(self) -> None:
        html = """
        <span class="my-price">$29.99</span>
        <span class="orig-price">$49.99</span>
        """
        strategy = CSSSelectorStrategy(
            product_config={"price": ".my-price", "original_price": ".orig-price"}
        )
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("29.99")
        assert result.original_price == Decimal("49.99")

    def test_no_matching_domain(self) -> None:
        html = "<span>$10.00</span>"
        strategy = CSSSelectorStrategy()
        result = strategy.extract(_make_soup(html), "https://unknowndomain.xyz/product")
        assert result is None

    def test_in_stock_button_missing(self) -> None:
        html = """
        <span class="my-price">$29.99</span>
        """
        strategy = CSSSelectorStrategy(
            product_config={
                "price": ".my-price",
                "in_stock": ".add-to-cart-button",
            }
        )
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is False

    def test_in_stock_button_present(self) -> None:
        html = """
        <span class="my-price">$29.99</span>
        <button class="add-to-cart-button">Add to Cart</button>
        """
        strategy = CSSSelectorStrategy(
            product_config={
                "price": ".my-price",
                "in_stock": ".add-to-cart-button",
            }
        )
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is True


# ─── Strategy 5: Regex Fallback ─────────────────────────────────────────


class TestRegexFallbackStrategy:
    """Tests for regex fallback extraction."""

    strategy = RegexFallbackStrategy()

    def test_price_in_class(self) -> None:
        html = '<div class="price-value">$24.99</div>'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("24.99")

    def test_price_in_id(self) -> None:
        html = '<span id="product-price">€15.00</span>'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("15.00")
        assert result.currency == "EUR"

    def test_data_price_attribute(self) -> None:
        html = '<div class="item" data-price="39.99">Item</div>'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("39.99")

    def test_no_price(self) -> None:
        html = "<body><p>No prices here.</p></body>"
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_price_in_body_text(self) -> None:
        html = "<body><p>This item costs $79.99 and ships free.</p></body>"
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("79.99")


# ─── Orchestrator / Confidence Scoring ──────────────────────────────────


class TestPriceExtractor:
    """Tests for the main PriceExtractor orchestrator."""

    def test_json_ld_only(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "99.99", "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }}
        </script>
        </head><body></body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com")
        assert result.success
        assert result.current_price == Decimal("99.99")
        assert result.currency == "USD"
        assert result.in_stock is True
        assert "json_ld" in result.strategies_used
        assert result.confidence >= 0.8

    def test_multiple_strategies_agree(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "49.99", "priceCurrency": "USD"
        }}
        </script>
        <meta property="og:price:amount" content="49.99">
        <meta property="og:price:currency" content="USD">
        </head>
        <body>
        <span itemprop="price" content="49.99">$49.99</span>
        <meta itemprop="priceCurrency" content="USD">
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com")
        assert result.success
        assert result.current_price == Decimal("49.99")
        # Multiple strategies should have extracted
        assert len(result.strategies_used) >= 3
        # High confidence because multiple strategies agree
        assert result.confidence >= 0.9

    def test_sale_price_detection(self) -> None:
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "19.99", "priceCurrency": "USD"
        }}
        </script>
        <meta property="product:price:amount" content="19.99">
        <meta property="product:sale_price:amount" content="19.99">
        <meta property="product:original_price:amount" content="39.99">
        <meta property="product:price:currency" content="USD">
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com")
        assert result.success
        assert result.current_price == Decimal("19.99")
        assert result.original_price == Decimal("39.99")

    def test_no_price_found(self) -> None:
        html = "<html><body><p>A page with no prices at all.</p></body></html>"
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com")
        assert not result.success
        assert result.current_price is None
        assert result.confidence == 0.0

    def test_custom_css_with_json_ld(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "29.99", "priceCurrency": "USD"
        }}
        </script>
        </head><body>
        <span class="custom-price">$29.99</span>
        </body></html>
        """
        extractor = PriceExtractor(
            product_selector_config={"price": ".custom-price"}
        )
        result = extractor.extract(html, "https://example.com")
        assert result.success
        assert result.current_price == Decimal("29.99")
        # Both JSON-LD and CSS should have found it
        assert "json_ld" in result.strategies_used
        assert "css_selector" in result.strategies_used

    def test_to_dict(self) -> None:
        result = ExtractionResult(
            current_price=Decimal("29.99"),
            original_price=Decimal("39.99"),
            sale_price=Decimal("29.99"),
            currency="USD",
            in_stock=True,
            confidence=0.95,
            strategies_used=["json_ld", "open_graph"],
        )
        d = result.to_dict()
        assert d["current_price"] == 29.99
        assert d["original_price"] == 39.99
        assert d["currency"] == "USD"
        assert d["confidence"] == 0.95
        assert d["strategies_used"] == ["json_ld", "open_graph"]


# ─── Real-world-like HTML fixtures ──────────────────────────────────────


class TestRealWorldScenarios:
    """Tests simulating real e-commerce page structures."""

    def test_shopify_product_page(self) -> None:
        """Simulate a typical Shopify product page."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "Product",
          "name": "Premium T-Shirt",
          "image": "https://cdn.shopify.com/s/files/image.jpg",
          "offers": {
            "@type": "Offer",
            "url": "https://myshop.myshopify.com/products/premium-tshirt",
            "priceCurrency": "USD",
            "price": "34.99",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        <meta property="og:price:amount" content="34.99">
        <meta property="og:price:currency" content="USD">
        </head>
        <body>
        <div class="product__price">
          <span class="price-item price-item--sale">$34.99</span>
          <span class="price-item--regular price-item--last">
            <s>$44.99</s>
          </span>
        </div>
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://myshop.myshopify.com/products/premium-tshirt")
        assert result.success
        assert result.current_price == Decimal("34.99")
        assert result.currency == "USD"
        assert result.in_stock is True
        assert result.confidence >= 0.8

    def test_amazon_like_page(self) -> None:
        """Simulate an Amazon-like product page."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Wireless Headphones",
          "offers": {
            "@type": "Offer",
            "price": "79.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        </head>
        <body>
        <span class="a-price"><span class="a-offscreen">$79.99</span></span>
        <span class="a-text-price"><span class="a-offscreen">$129.99</span></span>
        <div id="availability"><span>In Stock.</span></div>
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://www.amazon.com/dp/B0123456789")
        assert result.success
        assert result.current_price == Decimal("79.99")
        assert result.in_stock is True
        assert len(result.strategies_used) >= 2

    def test_european_store(self) -> None:
        """Test with European price formatting."""
        html = """
        <html><head>
        <meta property="og:price:amount" content="1234.56">
        <meta property="og:price:currency" content="EUR">
        <meta property="og:availability" content="instock">
        </head>
        <body>
        <span itemprop="price" content="1234.56">1.234,56 €</span>
        <meta itemprop="priceCurrency" content="EUR">
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.de/produkt/123")
        assert result.success
        assert result.current_price == Decimal("1234.56")
        assert result.currency == "EUR"

    def test_out_of_stock_product(self) -> None:
        """Test out-of-stock detection across strategies."""
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "59.99", "priceCurrency": "USD",
          "availability": "https://schema.org/OutOfStock"
        }}
        </script>
        <meta property="og:price:amount" content="59.99">
        <meta property="og:availability" content="out of stock">
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com/product")
        assert result.success
        assert result.current_price == Decimal("59.99")
        assert result.in_stock is False

    def test_minimal_page_regex_only(self) -> None:
        """Test page with only plain-text prices (regex fallback)."""
        html = """
        <html><body>
        <h1>Cool Gadget</h1>
        <div class="price-box">
          <span class="price">$199.00</span>
        </div>
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://unknown-store.com/gadget")
        assert result.success
        assert result.current_price == Decimal("199.00")
        assert "regex_fallback" in result.strategies_used

    def test_price_with_sale_inference(self) -> None:
        """Test that sale_price is inferred when original > current."""
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "24.99", "priceCurrency": "USD"
        }}
        </script>
        <meta property="product:price:amount" content="24.99">
        <meta property="product:original_price:amount" content="49.99">
        <meta property="product:price:currency" content="USD">
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com")
        assert result.success
        assert result.current_price == Decimal("24.99")
        assert result.original_price == Decimal("49.99")
        assert result.sale_price == Decimal("24.99")


# ─── PriceData / ExtractionResult unit tests ────────────────────────────


class TestPriceData:
    def test_has_price(self) -> None:
        pd = PriceData(current_price=Decimal("10.00"), strategy="test")
        assert pd.has_price is True

    def test_no_price(self) -> None:
        pd = PriceData(strategy="test")
        assert pd.has_price is False


class TestExtractionResult:
    def test_success_true(self) -> None:
        r = ExtractionResult(current_price=Decimal("1.00"))
        assert r.success is True

    def test_success_false(self) -> None:
        r = ExtractionResult()
        assert r.success is False

    def test_to_dict_none_prices(self) -> None:
        r = ExtractionResult()
        d = r.to_dict()
        assert d["current_price"] is None
        assert d["original_price"] is None


# ─── Audit Bug-Fix Regression Tests ─────────────────────────────────────


class TestAuditFixes:
    """Regression tests for bugs found during the Phase 1 audit."""

    def test_json_ld_main_entity(self) -> None:
        """JSON-LD with mainEntity nesting (common on WooCommerce)."""
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "WebPage",
          "mainEntity": {
            "@type": "Product",
            "name": "Widget",
            "offers": {
              "@type": "Offer",
              "price": "42.00",
              "priceCurrency": "USD"
            }
          }
        }
        </script>
        """
        strategy = JsonLdStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("42.00")

    def test_json_ld_product_group(self) -> None:
        """JSON-LD with ProductGroup type (grouped variants)."""
        html = """
        <script type="application/ld+json">
        {
          "@type": "ProductGroup",
          "name": "T-Shirt",
          "offers": {
            "@type": "AggregateOffer",
            "lowPrice": "19.99",
            "priceCurrency": "USD"
          }
        }
        </script>
        """
        strategy = JsonLdStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("19.99")

    def test_json_ld_zero_price_rejected(self) -> None:
        """Zero price should be rejected (often means 'call for price')."""
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "0.00", "priceCurrency": "USD"
        }}
        </script>
        """
        strategy = JsonLdStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_json_ld_zero_aggregate_rejected(self) -> None:
        """Zero lowPrice in AggregateOffer should be rejected."""
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "AggregateOffer", "lowPrice": "0", "priceCurrency": "USD"
        }}
        </script>
        """
        strategy = JsonLdStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_json_ld_preorder_is_in_stock(self) -> None:
        """PreOrder should be treated as in-stock (product CAN be purchased)."""
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "59.99", "priceCurrency": "USD",
          "availability": "https://schema.org/PreOrder"
        }}
        </script>
        """
        strategy = JsonLdStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.in_stock is True

    def test_og_zero_price_rejected(self) -> None:
        """Open Graph zero price should be rejected."""
        html = '<meta property="og:price:amount" content="0.00">'
        strategy = OpenGraphStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_microdata_zero_price_rejected(self) -> None:
        """Microdata zero price should be rejected."""
        html = '<span itemprop="price" content="0">$0.00</span>'
        strategy = MicrodataStrategy()
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_css_selector_zero_price_rejected(self) -> None:
        """CSS selector zero price should be rejected."""
        html = '<span class="my-price">$0.00</span>'
        strategy = CSSSelectorStrategy(product_config={"price": ".my-price"})
        result = strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_pln_ascii_zl_detection(self) -> None:
        """ASCII 'zl' should be detected as PLN currency."""
        assert detect_currency("99.99 zl") == "PLN"

    def test_pln_unicode_zl_detection(self) -> None:
        """Unicode 'zł' should be detected as PLN currency."""
        assert detect_currency("99.99 zł") == "PLN"

    def test_confidence_includes_usd(self) -> None:
        """Confidence completeness bonus should work for USD too."""
        html = """
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "29.99", "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }}
        </script>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com")
        # USD should get the completeness bonus (currency detected)
        assert result.confidence >= 0.9  # base 1.0 + completeness bonuses

    def test_select_best_price_no_mutation(self) -> None:
        """_select_best_price should not mutate the input list order."""
        from price_radar.application.price_extraction.extractor import PriceExtractor as PE

        results = [
            PriceData(current_price=Decimal("10.00"), strategy="regex_fallback"),
            PriceData(current_price=Decimal("20.00"), strategy="json_ld"),
            PriceData(current_price=Decimal("30.00"), strategy="css_selector"),
        ]
        original_order = [r.current_price for r in results]
        PE._select_best_price(results)
        after_order = [r.current_price for r in results]
        assert original_order == after_order, "Input list was mutated!"


# ─── Strategy 6: Script Tag Data ─────────────────────────────────────


class TestScriptTagStrategy:
    """Tests for embedded script data extraction (__NEXT_DATA__, __INITIAL_STATE__)."""

    strategy = ScriptTagStrategy()

    def test_next_data_basic(self) -> None:
        """Extract price from a Next.js __NEXT_DATA__ payload."""
        html = """
        <html><head></head><body>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "title": "Cool Widget",
                "price": "49.99",
                "currency": "USD",
                "available": true
              }
            }
          }
        }
        </script>
        </body></html>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com/product")
        assert result is not None
        assert result.current_price == Decimal("49.99")
        assert result.currency == "USD"
        assert result.in_stock is True
        assert result.strategy == "script_tag"

    def test_next_data_nested_pricing(self) -> None:
        """Extract price from deeply nested Next.js data."""
        html = """
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "initialData": {
                "data": {
                  "product": {
                    "pricing": {
                      "currentPrice": "129.00",
                      "regularPrice": "159.00",
                      "currencyCode": "EUR"
                    }
                  }
                }
              }
            }
          }
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.de/produkt")
        assert result is not None
        assert result.current_price == Decimal("129.00")

    def test_next_data_with_compare_at_price(self) -> None:
        """Extract price + original price from Next.js data."""
        html = """
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "price": "24.99",
                "compare_at_price": "39.99",
                "currency": "USD",
                "available": true
              }
            }
          }
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("24.99")
        assert result.original_price == Decimal("39.99")

    def test_next_data_out_of_stock(self) -> None:
        """Detect out-of-stock from Next.js data."""
        html = """
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "price": "99.99",
                "available": false
              }
            }
          }
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("99.99")
        assert result.in_stock is False

    def test_initial_state_redux(self) -> None:
        """Extract price from window.__INITIAL_STATE__ (Redux)."""
        html = """
        <html><body>
        <script>
        window.__INITIAL_STATE__ = {
          "product": {
            "item": {
              "price": "59.99",
              "currency": "GBP",
              "inStock": true
            }
          }
        };
        </script>
        </body></html>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.co.uk")
        assert result is not None
        assert result.current_price == Decimal("59.99")
        assert result.currency == "GBP"

    def test_preloaded_state(self) -> None:
        """Extract price from window.__PRELOADED_STATE__."""
        html = """
        <script>
        window.__PRELOADED_STATE__ = {
          "pdpData": {
            "price": "199.00",
            "currencyCode": "USD",
            "availability": "InStock"
          }
        };
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is not None
        assert result.current_price == Decimal("199.00")

    def test_shopify_inline_variants(self) -> None:
        """Extract price from Shopify inline variant JSON."""
        html = """
        <script>
        var product = {
          "title": "Test Product",
          "variants": [{"id": 123, "price": "29.99", "compare_at_price": "49.99", "available": true}]
        };
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.myshopify.com/products/test")
        assert result is not None
        assert result.current_price == Decimal("29.99")
        assert result.original_price == Decimal("49.99")
        assert result.in_stock is True

    def test_shopify_inline_cents_format(self) -> None:
        """Shopify sometimes stores prices in cents (integer, no decimal)."""
        html = """
        <script>
        var data = {
          "variants": [{"id": 1, "price": "2999", "available": true}]
        };
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://store.myshopify.com/products/item")
        assert result is not None
        # 2999 cents -> 29.99
        assert result.current_price == Decimal("29.99")

    def test_no_script_data(self) -> None:
        """Return None when no recognizable script data is present."""
        html = "<html><body><p>Just plain HTML</p></body></html>"
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_invalid_next_data_json(self) -> None:
        """Gracefully handle malformed __NEXT_DATA__ JSON."""
        html = '<script id="__NEXT_DATA__" type="application/json">{ invalid json }</script>'
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_next_data_no_price_fields(self) -> None:
        """Return None when __NEXT_DATA__ exists but has no price fields."""
        html = """
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "seoData": {"title": "Home Page"},
              "navigation": [{"label": "Shop"}]
            }
          }
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_zero_price_rejected(self) -> None:
        """Zero price from script data should be rejected."""
        html = """
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {"price": "0.00", "currency": "USD"}
            }
          }
        }
        </script>
        """
        result = self.strategy.extract(_make_soup(html), "https://example.com")
        assert result is None

    def test_orchestrator_uses_script_tag(self) -> None:
        """Full orchestrator should use script_tag strategy for Next.js pages."""
        html = """
        <html><head></head><body>
        <div id="__next"></div>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "price": "79.99",
                "currency": "USD",
                "available": true
              }
            }
          }
        }
        </script>
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com/product/123")
        assert result.success
        assert result.current_price == Decimal("79.99")
        assert "script_tag" in result.strategies_used


# ─── Strategy 7: Shopify JSON API ────────────────────────────────────


class TestShopifyApiStrategy:
    """Tests for Shopify JSON API strategy.

    NOTE: These tests cover detection and parsing logic only, not live API calls.
    Live API tests are in the integration test suite.
    """

    strategy = ShopifyApiStrategy()

    def test_detect_myshopify_domain(self) -> None:
        """Detect .myshopify.com domains."""
        html = "<html><body></body></html>"
        soup = _make_soup(html)
        assert self.strategy._is_shopify(soup, "https://my-store.myshopify.com/products/item")

    def test_detect_known_shopify_domain(self) -> None:
        """Detect known Shopify custom domains."""
        html = "<html><body></body></html>"
        soup = _make_soup(html)
        assert self.strategy._is_shopify(soup, "https://www.gymshark.com/products/leggings")

    def test_detect_shopify_cdn_in_html(self) -> None:
        """Detect Shopify via CDN references in HTML."""
        html = """
        <html><head>
        <link rel="stylesheet" href="https://cdn.shopify.com/s/files/1/theme.css">
        </head><body></body></html>
        """
        soup = _make_soup(html)
        assert self.strategy._is_shopify(soup, "https://unknown-store.com/products/item")

    def test_detect_shopify_meta_generator(self) -> None:
        """Detect Shopify via meta generator tag."""
        html = '<html><head><meta name="generator" content="Shopify"></head><body></body></html>'
        soup = _make_soup(html)
        assert self.strategy._is_shopify(soup, "https://unknown-store.com/products/item")

    def test_detect_shopify_analytics(self) -> None:
        """Detect Shopify via ShopifyAnalytics in script."""
        html = """
        <html><body>
        <script>window.ShopifyAnalytics = {meta: {}};</script>
        </body></html>
        """
        soup = _make_soup(html)
        assert self.strategy._is_shopify(soup, "https://custom-store.com/products/tee")

    def test_not_shopify(self) -> None:
        """Non-Shopify sites should not be detected."""
        html = "<html><body><p>Just a regular site</p></body></html>"
        soup = _make_soup(html)
        assert not self.strategy._is_shopify(soup, "https://www.amazon.com/dp/B123")

    def test_extract_handle_basic(self) -> None:
        """Extract handle from standard /products/handle URL."""
        handle = ShopifyApiStrategy._extract_handle("https://store.com/products/cool-widget")
        assert handle == "cool-widget"

    def test_extract_handle_with_collection(self) -> None:
        """Extract handle from /collections/.../products/handle URL."""
        handle = ShopifyApiStrategy._extract_handle(
            "https://store.com/collections/summer/products/beach-towel"
        )
        assert handle == "beach-towel"

    def test_extract_handle_no_products_path(self) -> None:
        """Return None for non-product URLs."""
        handle = ShopifyApiStrategy._extract_handle("https://store.com/about")
        assert handle is None

    def test_extract_handle_trailing_slash(self) -> None:
        """Handle trailing slash in URL."""
        handle = ShopifyApiStrategy._extract_handle("https://store.com/products/my-item/")
        assert handle == "my-item"

    def test_parse_product_basic(self) -> None:
        """Parse a basic Shopify product JSON response."""
        product = {
            "title": "Test Product",
            "variants": [
                {
                    "id": 1,
                    "price": "29.99",
                    "compare_at_price": None,
                    "available": True,
                }
            ],
        }
        result = self.strategy._parse_product(product)
        assert result is not None
        assert result.current_price == Decimal("29.99")
        assert result.original_price is None
        assert result.in_stock is True

    def test_parse_product_with_sale(self) -> None:
        """Parse product with compare_at_price (sale)."""
        product = {
            "title": "Sale Item",
            "variants": [
                {
                    "id": 1,
                    "price": "19.99",
                    "compare_at_price": "39.99",
                    "available": True,
                }
            ],
        }
        result = self.strategy._parse_product(product)
        assert result is not None
        assert result.current_price == Decimal("19.99")
        assert result.original_price == Decimal("39.99")
        assert result.sale_price == Decimal("19.99")

    def test_parse_product_out_of_stock(self) -> None:
        """Parse product where first variant is unavailable."""
        product = {
            "title": "Sold Out Item",
            "variants": [
                {
                    "id": 1,
                    "price": "49.99",
                    "available": False,
                }
            ],
        }
        result = self.strategy._parse_product(product)
        assert result is not None
        assert result.current_price == Decimal("49.99")
        assert result.in_stock is False

    def test_parse_product_multiple_variants(self) -> None:
        """Should pick first available variant."""
        product = {
            "title": "Multi-Variant Product",
            "variants": [
                {"id": 1, "price": "59.99", "available": False},
                {"id": 2, "price": "69.99", "available": True},
                {"id": 3, "price": "79.99", "available": True},
            ],
        }
        result = self.strategy._parse_product(product)
        assert result is not None
        # Should pick variant 2 (first available)
        assert result.current_price == Decimal("69.99")
        assert result.in_stock is True

    def test_parse_product_no_variants(self) -> None:
        """Return None when product has no variants."""
        product = {"title": "Empty Product", "variants": []}
        result = self.strategy._parse_product(product)
        assert result is None

    def test_parse_product_zero_price(self) -> None:
        """Reject zero-priced variants."""
        product = {
            "title": "Free Product",
            "variants": [{"id": 1, "price": "0.00", "available": True}],
        }
        result = self.strategy._parse_product(product)
        assert result is None

    def test_non_shopify_url_returns_none(self) -> None:
        """Strategy should return None for non-Shopify URLs."""
        html = "<html><body><p>Regular site</p></body></html>"
        result = self.strategy.extract(_make_soup(html), "https://www.amazon.com/dp/B123")
        assert result is None

    def test_strategy_registered_in_extractor(self) -> None:
        """Verify shopify_api strategy is in the extractor pipeline."""
        extractor = PriceExtractor()
        names = [s.name for s in extractor._strategies]
        assert "shopify_api" in names
        # Should be before open_graph but after json_ld
        json_ld_idx = names.index("json_ld")
        shopify_idx = names.index("shopify_api")
        og_idx = names.index("open_graph")
        assert json_ld_idx < shopify_idx < og_idx

    def test_strategy_weight(self) -> None:
        """Verify shopify_api has correct weight."""
        from price_radar.application.price_extraction.extractor import STRATEGY_WEIGHTS
        assert STRATEGY_WEIGHTS["shopify_api"] == 0.95
        assert STRATEGY_WEIGHTS["script_tag"] == 0.92


# ─── Pipeline Integration Tests (both new strategies) ────────────────


class TestNewStrategiesPipeline:
    """Tests verifying the 7-strategy pipeline works correctly end-to-end."""

    def test_pipeline_has_seven_strategies(self) -> None:
        """Extractor should now have 7 strategies in correct order."""
        extractor = PriceExtractor()
        names = [s.name for s in extractor._strategies]
        assert names == [
            "json_ld", "shopify_api", "script_tag",
            "open_graph", "microdata", "css_selector", "regex_fallback",
        ]

    def test_next_data_plus_json_ld(self) -> None:
        """When both JSON-LD and __NEXT_DATA__ are present, both should be used."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "offers": {
          "@type": "Offer", "price": "49.99", "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }}
        </script>
        </head><body>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {
                "price": "49.99",
                "currency": "USD",
                "available": true
              }
            }
          }
        }
        </script>
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.com/product")
        assert result.success
        assert result.current_price == Decimal("49.99")
        assert "json_ld" in result.strategies_used
        assert "script_tag" in result.strategies_used
        # High confidence because multiple high-weight strategies agree
        assert result.confidence >= 0.95

    def test_script_tag_only_page(self) -> None:
        """Page with only __NEXT_DATA__ (no JSON-LD/OG/microdata) should succeed."""
        html = """
        <html><head></head><body>
        <div id="__next"><div>Loading...</div></div>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "product": {"price": "34.99", "currency": "EUR"}
            }
          }
        }
        </script>
        </body></html>
        """
        extractor = PriceExtractor()
        result = extractor.extract(html, "https://example.de/produkt/123")
        assert result.success
        assert result.current_price == Decimal("34.99")
        assert result.currency == "EUR"
        assert "script_tag" in result.strategies_used
