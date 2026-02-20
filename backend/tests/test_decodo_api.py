"""Tests for the Decodo Web Scraping API client.

Unit tests use mocks — no real API calls are made.

Run:
    PYTHONPATH=src python -m pytest tests/test_decodo_api.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from price_radar.application.price_extraction.decodo_api import (
    DecodoApiClient,
    DecodoApiResult,
)


# ── DecodoApiResult tests ───────────────────────────────────────────────


class TestDecodoApiResult:
    def test_success_when_html_large_enough(self) -> None:
        r = DecodoApiResult(url="https://example.com", html="<html>" + "x" * 600, html_size=606)
        assert r.success is True

    def test_failure_when_no_html(self) -> None:
        r = DecodoApiResult(url="https://example.com")
        assert r.success is False

    def test_failure_when_html_too_small(self) -> None:
        r = DecodoApiResult(url="https://example.com", html="<html>tiny", html_size=10)
        assert r.success is False

    def test_failure_when_html_is_none(self) -> None:
        r = DecodoApiResult(url="https://example.com", html=None, html_size=0)
        assert r.success is False

    def test_default_values(self) -> None:
        r = DecodoApiResult(url="https://example.com")
        assert r.status_code is None
        assert r.error is None
        assert r.fetch_time == 0.0
        assert r.html_size == 0


# ── DecodoApiClient configuration tests ─────────────────────────────────


class TestDecodoApiClientConfig:
    def test_is_configured_with_credentials(self) -> None:
        client = DecodoApiClient(username="user", password="pass")
        assert client.is_configured is True

    def test_not_configured_with_empty_username(self) -> None:
        client = DecodoApiClient(username="", password="pass")
        assert client.is_configured is False

    def test_not_configured_with_empty_password(self) -> None:
        client = DecodoApiClient(username="user", password="")
        assert client.is_configured is False

    def test_not_configured_with_both_empty(self) -> None:
        client = DecodoApiClient(username="", password="")
        assert client.is_configured is False


# ── DecodoApiClient.fetch() tests (mocked HTTP) ─────────────────────────


class TestDecodoApiClientFetch:
    def _make_client(self, **kwargs) -> DecodoApiClient:
        defaults = {"username": "testuser", "password": "testpass"}
        defaults.update(kwargs)
        return DecodoApiClient(**defaults)

    def test_returns_not_configured_when_no_credentials(self) -> None:
        client = DecodoApiClient(username="", password="")
        result = client.fetch("https://example.com")
        assert not result.success
        assert result.error == "decodo_api_not_configured"

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_successful_fetch_results_array_format(self, mock_post: MagicMock) -> None:
        """API response with results array (most common format)."""
        html = "<html><body>" + "x" * 600 + "</body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [{"content": html}]
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.fetch("https://www.target.com/p/item")

        assert result.success
        assert result.html == html
        assert result.html_size == len(html)
        assert result.status_code == 200
        assert result.error is None
        assert result.fetch_time > 0

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_successful_fetch_top_level_content_format(self, mock_post: MagicMock) -> None:
        """API response with top-level content field."""
        html = "<html><body>" + "x" * 600 + "</body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": html}
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.fetch("https://www.target.com/p/item")

        assert result.success
        assert result.html == html

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_empty_response_returns_error(self, mock_post: MagicMock) -> None:
        """API returns 200 but no usable content."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert result.error == "decodo_api_empty_response"

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_auth_failure_401(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert result.error == "decodo_api_auth_failed"
        assert result.status_code == 401

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_invalid_params_422(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Invalid URL parameter"
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert "decodo_api_invalid_params" in result.error
        assert result.status_code == 422

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_other_http_error(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert result.error == "decodo_api_http_500"

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_timeout_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.ReadTimeout("Connection timed out")

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert result.error == "decodo_api_timeout"

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_connection_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.ConnectError("DNS resolution failed")

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert "decodo_api_error: ConnectError" in result.error

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_unexpected_exception(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = RuntimeError("unexpected")

        client = self._make_client()
        result = client.fetch("https://example.com")

        assert not result.success
        assert "RuntimeError" in result.error

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_request_payload_includes_headless(self, mock_post: MagicMock) -> None:
        """Verify the POST payload includes headless=html by default."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"content": "x" * 600}]}
        mock_post.return_value = mock_resp

        client = self._make_client()
        client.fetch("https://www.target.com/p/item")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["target"] == "universal"
        assert payload["url"] == "https://www.target.com/p/item"
        assert payload["headless"] == "html"
        assert payload["geo"] == "United States"
        assert payload["device_type"] == "desktop"

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_request_payload_without_headless(self, mock_post: MagicMock) -> None:
        """When headless=None, the payload should NOT include headless."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"content": "x" * 600}]}
        mock_post.return_value = mock_resp

        client = self._make_client(headless=None)
        client.fetch("https://example.com")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "headless" not in payload

    @patch("price_radar.application.price_extraction.decodo_api.httpx.post")
    def test_auth_credentials_passed(self, mock_post: MagicMock) -> None:
        """Verify HTTP Basic Auth credentials are passed to httpx."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"content": "x" * 600}]}
        mock_post.return_value = mock_resp

        client = self._make_client(username="myuser", password="mypass")
        client.fetch("https://example.com")

        call_kwargs = mock_post.call_args
        auth = call_kwargs.kwargs.get("auth") or call_kwargs[1].get("auth")
        assert auth == ("myuser", "mypass")


# ── _extract_content static method tests ─────────────────────────────────


class TestExtractContent:
    def test_results_array_format(self) -> None:
        data = {"results": [{"content": "<html>page</html>"}]}
        assert DecodoApiClient._extract_content(data) == "<html>page</html>"

    def test_top_level_content(self) -> None:
        data = {"content": "<html>page</html>"}
        assert DecodoApiClient._extract_content(data) == "<html>page</html>"

    def test_empty_results_array(self) -> None:
        data = {"results": []}
        assert DecodoApiClient._extract_content(data) is None

    def test_results_without_content(self) -> None:
        data = {"results": [{"status": "ok"}]}
        assert DecodoApiClient._extract_content(data) is None

    def test_empty_dict(self) -> None:
        data = {}
        assert DecodoApiClient._extract_content(data) is None

    def test_results_array_multiple_items(self) -> None:
        """Should return the first result's content."""
        data = {"results": [
            {"content": "<html>first</html>"},
            {"content": "<html>second</html>"},
        ]}
        assert DecodoApiClient._extract_content(data) == "<html>first</html>"
