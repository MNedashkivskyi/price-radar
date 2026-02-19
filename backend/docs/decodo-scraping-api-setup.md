# Decodo Scraping API Setup Guide

The Decodo (formerly Smartproxy) Web Scraping API is the **last-resort fetch
tier** in the Price Radar scraping pipeline. It handles proxies, browser
rendering, CAPTCHA solving, and anti-bot bypass internally, returning clean
HTML.

## When is it used?

The scraping pipeline has three tiers:

| Tier | Method | Speed | When used |
|------|--------|-------|-----------|
| 1 | **httpx** | ~1-3s | Default for most sites. Fast HTTP GET. |
| 2 | **Playwright** | ~5-15s | Sites requiring JavaScript rendering (CSR). |
| 3 | **Decodo Scraping API** | ~5-30s | Last resort when Tier 1 & 2 fail with CAPTCHA/bot-wall. |

The Decodo API is triggered automatically when:
- Playwright detects a CAPTCHA / bot-wall (`captcha_detected`)
- Playwright crashes with a protocol error (`playwright_error`)
- The fetch returns empty HTML (`fetch_failed`)

If the Decodo API is **not configured**, the pipeline simply stops at Tier 2
and reports the failure. There is **no degradation** in existing behavior.

## Prerequisites

1. A **Decodo account** at [decodo.com](https://decodo.com)
2. An active **Web Scraping API** subscription
   - **Core** plan: raw HTTP scraping (no JS rendering)
   - **Advanced** plan: full JavaScript rendering via `headless=html` (recommended)

## Getting Your Credentials

1. Log in to the [Decodo Dashboard](https://dashboard.decodo.com)
2. Navigate to **Scraping** in the left sidebar
3. Click the **Authentication** tab
4. You will see:
   - **Username** (e.g. `spXXXXXXXX`)
   - **Password** (auto-generated, can be regenerated)
5. Copy both values

## Configuration

Add these environment variables to your `.env` file (or your deployment
environment):

```bash
# Decodo Web Scraping API (last-resort tier)
DECODO_API_USERNAME=spXXXXXXXX
DECODO_API_PASSWORD=your_password_here
```

These are **separate** from the residential proxy URL (`DECODO_PROXY_URL`)
which uses a different authentication mechanism.

### Full `.env` example with all Decodo settings:

```bash
# Residential proxy (Tier 1 & 2 - used for httpx and Playwright)
DECODO_PROXY_URL=http://user:pass@gate.smartproxy.com:10001

# Scraping API (Tier 3 - last resort for CAPTCHA-blocked sites)
DECODO_API_USERNAME=spXXXXXXXX
DECODO_API_PASSWORD=your_password_here
```

## Verification

### Quick test (Python):

```python
from price_radar.application.price_extraction.decodo_api import DecodoApiClient

client = DecodoApiClient(
    username="spXXXXXXXX",
    password="your_password_here",
)
result = client.fetch("https://www.target.com/p/keurig-k-mini/-/A-53448183")

print(f"Success: {result.success}")
print(f"HTML size: {result.html_size} bytes")
print(f"Time: {result.fetch_time:.1f}s")
print(f"Error: {result.error}")
```

### Run the 50-site scrape test:

```bash
cd backend
PYTHONPATH=src python -m pytest tests/test_50_sites_scrape.py -v -s -m live
```

The test output will show the Decodo API status at the top:

```
==========================================================================================
  PROXY & API CONFIGURATION
==========================================================================================
  DECODO_PROXY_URL set:      True
  Proxy endpoint:            http://user:****@gate.smartproxy.com:10001
  DECODO_API configured:     True
  Known residential domains: 38
  Direct domains:            9
==========================================================================================
```

Sites that fail with CAPTCHA on Playwright will automatically fall back to
the Decodo API. The `fetch_method` column will show `decodo_api` for these:

```
  [12/47] Scraping macys.com        (residential) ... OK decodo_api   $29.99  12.3s
```

## API Details

| Setting | Value |
|---------|-------|
| Endpoint | `POST https://scraper-api.decodo.com/v2/scrape` |
| Auth | HTTP Basic Auth (username:password) |
| Target | `universal` (general web scraping) |
| JS rendering | `headless: "html"` (requires Advanced plan) |
| Geo | `United States` (default) |
| Device | `desktop` (default) |
| Timeout | 60 seconds |

### Request payload:

```json
{
  "target": "universal",
  "url": "https://www.target.com/p/...",
  "headless": "html",
  "geo": "United States",
  "device_type": "desktop"
}
```

### Response format:

```json
{
  "results": [
    {
      "content": "<html>...</html>",
      "status_code": 200,
      "url": "https://www.target.com/p/...",
      "task_id": "abc123",
      "created_at": "2025-01-01T00:00:00Z",
      "updated_at": "2025-01-01T00:00:05Z"
    }
  ]
}
```

## Cost Considerations

The Decodo Scraping API charges per request. To minimize costs:

- The API is only called as a **last resort** (after httpx and Playwright fail)
- It only triggers on specific errors: `captcha_detected`, `playwright_error`,
  `fetch_failed`
- It does NOT trigger on extraction failures (price not found in valid HTML)
- In practice, only ~10-15 sites out of 47 tested need the API fallback

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `decodo_api_not_configured` | Missing credentials | Set `DECODO_API_USERNAME` and `DECODO_API_PASSWORD` |
| `decodo_api_auth_failed` | Wrong credentials (HTTP 401) | Check username/password in Decodo dashboard |
| `decodo_api_invalid_params` | Bad request (HTTP 422) | Check API subscription is active |
| `decodo_api_timeout` | Request took > 60s | Site may be unreachable; retry later |
| `decodo_api_empty_response` | API returned no HTML | Site may be blocked even for Decodo |
| `decodo_api_http_429` | Rate limited | Reduce request frequency or upgrade plan |

## Architecture

```
PageFetcher.fetch_and_extract(url)
    |
    +-- Tier 1: _fetch_httpx(url)          # Fast HTTP GET (~1-3s)
    |   |
    |   +-- Auto-escalate on 403/429       # DIRECT -> RESIDENTIAL proxy
    |
    +-- Tier 2: _fetch_playwright(url)     # Headless Chromium (~5-15s)
    |   |
    |   +-- CAPTCHA detection              # Early exit on bot-wall
    |   +-- Adaptive price polling         # Wait for JS rendering
    |
    +-- Tier 3: _fetch_decodo_api(url)     # Decodo Scraping API (~5-30s)
        |
        +-- Only if Tier 1 & 2 failed with CAPTCHA/error
        +-- Handles anti-bot internally
        +-- Returns clean rendered HTML
```
