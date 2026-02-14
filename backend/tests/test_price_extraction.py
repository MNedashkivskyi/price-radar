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
