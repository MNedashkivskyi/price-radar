# Decodo (Smartproxy) Residential Proxy Setup

This guide covers how to configure the Decodo residential proxy integration
for Price Radar, including local development and Railway deployment.

## Overview

Price Radar uses a two-tier proxy system:

| Tier | Description | Use Case |
|------|-------------|----------|
| **DIRECT** | No proxy, direct connection | Most e-commerce sites |
| **RESIDENTIAL** | Decodo/Smartproxy residential IP | Sites that block datacenter IPs (Amazon, Allegro, Zalando, etc.) |

The `ProxyResolver` component automatically determines which tier to use
per domain. Known hard domains are pre-configured as RESIDENTIAL.
Unknown domains start as DIRECT; if they return 403/429, they are
automatically escalated to RESIDENTIAL for future requests.

## Architecture

```
                      +--------------------+
                      |   ProxyResolver    |
                      |  (per-domain tier) |
                      +--------+-----------+
                               |
              +----------------+----------------+
              |                                 |
    +---------v----------+           +----------v----------+
    |  DIRECT (no proxy) |           |  RESIDENTIAL proxy  |
    |  httpx / Playwright|           |  httpx / Playwright  |
    +--------------------+           +---------------------+
                                              |
                                     +--------v--------+
                                     |  Decodo Gateway  |
                                     | gate.smartproxy  |
                                     |   .com:10001     |
                                     +-----------------+
```

## 1. Get Decodo Credentials

1. Sign up at [Decodo (Smartproxy)](https://decodo.com)
2. Navigate to **Residential Proxies** > **Setup**
3. Note your credentials:
   - **Username** (e.g., `spXXXXXXXX`)
   - **Password**
   - **Endpoint**: `gate.smartproxy.com`
   - **Port**: `10001` (rotating session) or `10000` (sticky session)
4. Construct your proxy URL:
   ```
   http://USERNAME:PASSWORD@gate.smartproxy.com:10001
   ```

## 2. Local Development Setup

### Option A: Using `.env` file

Create or update `backend/.env`:

```env
# Decodo residential proxy
DECODO_PROXY_URL=http://spXXXXXXXX:your_password@gate.smartproxy.com:10001

# Optional: proxy tier TTL (days before re-classifying domains)
PROXY_TIER_TTL_DAYS=7
```

### Option B: Direct export

```bash
export DECODO_PROXY_URL="http://spXXXXXXXX:your_password@gate.smartproxy.com:10001"
```

### Option C: No proxy (default)

Leave `DECODO_PROXY_URL` empty or unset. All requests will go direct.
The scraping engine will work without proxy, but some protected sites
(Amazon, Allegro, Zalando) will likely fail.

### Verify Configuration

```python
from price_radar.infrastructure.config import settings
print(f"Proxy URL configured: {bool(settings.decodo_proxy_url)}")

from price_radar.application.proxy_resolver import ProxyResolver
resolver = ProxyResolver(proxy_url=settings.decodo_proxy_url)
print(resolver.get_tier_info("amazon.com"))
# {'domain': 'amazon.com', 'tier': 'residential', 'source': 'known_residential', 'proxy_configured': 'True'}
```

## 3. Railway Deployment

### Step 1: Add Environment Variables

In your Railway project dashboard:

1. Navigate to your **backend** service
2. Go to **Settings** > **Variables**
3. Add the following variables:

| Variable | Value | Required |
|----------|-------|----------|
| `DECODO_PROXY_URL` | `http://spXXXXXXXX:password@gate.smartproxy.com:10001` | Yes |
| `PROXY_TIER_TTL_DAYS` | `7` | No (default: 7) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Yes (already set) |
| `REDIS_URL` | `redis://...` | Yes (already set) |

4. Repeat for the **celery-worker** service (same variables)
5. Repeat for the **celery-beat** service (same variables)

> **Important**: All services that run scraping tasks need the proxy URL.
> This includes `backend`, `celery-worker`, and `celery-beat`.

### Step 2: Run Database Migration

After deploying, run the migration to create the `domain_proxy_tiers` table:

```bash
# Via Railway CLI
railway run alembic upgrade head

# Or via Railway dashboard > Service > Shell
cd /app && alembic upgrade head
```

### Step 3: Verify Deployment

Check that the proxy is configured:

```bash
# Via Railway CLI
railway run python -c "from price_radar.infrastructure.config import settings; print('Proxy:', bool(settings.decodo_proxy_url))"
```

### Step 4: Monitor Proxy Usage

Proxy usage is tracked in Redis metrics. You can check:

```bash
# Via the monitoring API
curl https://your-app.railway.app/internal/metrics/health \
  -H "X-API-Key: your-monitoring-api-key"
```

The response includes `proxy:direct` and `proxy:residential` counters
per domain, allowing you to monitor proxy bandwidth costs.

## 4. How Proxy Routing Works

### Pre-configured Domains

The following domains are always routed through RESIDENTIAL proxy:

- **Marketplaces**: `amazon.com`, `allegro.pl`, `ceneo.pl`, `zalando.*`
- **Retailers**: `target.com`, `bestbuy.com`, `homedepot.com`, `lowes.com`,
  `wayfair.com`, `nordstrom.com`, `macys.com`, `sephora.com`, `ulta.com`
- **Fashion**: `nike.com`, `adidas.com`, `zara.com`, `hm.com`, `uniqlo.com`, `asos.com`
- **Tech**: `newegg.com`, `bhphotovideo.com`

### Automatic Escalation

For unknown domains:

1. First request goes **DIRECT** (no proxy)
2. If the response is **403 Forbidden** or **429 Too Many Requests**:
   - The domain is **escalated** to RESIDENTIAL
   - The request is **retried** through the residential proxy
   - The classification is **cached in Redis** for 7 days
3. Future requests to that domain use RESIDENTIAL directly

### Redis Cache

Domain classifications are stored in Redis:

```
proxy:tier:example.com  →  "residential"  (TTL: 7 days)
```

When Redis is unavailable, classifications are cached in-process memory.

## 5. Cost Monitoring

Decodo charges per GB of residential traffic. To monitor costs:

1. **Redis metrics**: Each scrape records `proxy:direct` or `proxy:residential`
   in the per-domain daily stats hash. Query via the monitoring API.

2. **Decodo dashboard**: Check your usage at https://dashboard.smartproxy.com

3. **Estimated costs**:
   - Average page size: ~500 KB
   - Residential requests per day (estimate): depends on domain mix
   - Decodo residential rate: check your plan pricing

### Tips to Minimize Proxy Costs

- Let the auto-escalation work — don't force all domains to RESIDENTIAL
- Use `PROXY_TIER_TTL_DAYS=7` (default) to periodically re-check if
  domains still need residential proxy
- Monitor the `proxy:residential` counter in metrics to identify
  high-traffic domains that might be worth optimizing

## 6. Docker Compose (Local)

If running via Docker Compose, add the proxy URL to all scraping services:

```yaml
# docker-compose.yml
services:
  backend:
    environment:
      - DECODO_PROXY_URL=http://spXXXXXXXX:password@gate.smartproxy.com:10001

  celery-worker:
    environment:
      - DECODO_PROXY_URL=http://spXXXXXXXX:password@gate.smartproxy.com:10001

  celery-beat:
    environment:
      - DECODO_PROXY_URL=http://spXXXXXXXX:password@gate.smartproxy.com:10001
```

Or use an `.env` file referenced by all services:

```yaml
services:
  backend:
    env_file:
      - ./backend/.env
```

## 7. Troubleshooting

### Proxy not working

```python
# Test the proxy directly
import httpx
resp = httpx.get(
    "https://httpbin.org/ip",
    proxy="http://spXXXXXXXX:password@gate.smartproxy.com:10001",
    timeout=30,
)
print(resp.json())  # Should show a residential IP, not your server IP
```

### Domain still failing with proxy

Some sites use more than IP-based blocking (TLS fingerprinting, JS challenges).
In this case, Playwright + proxy is usually needed. Check if the domain is in
`PLAYWRIGHT_DOMAINS` in `fetcher.py`.

### Redis connection errors

The proxy resolver degrades gracefully: if Redis is unavailable, it falls
back to in-memory caching. Check Redis connectivity:

```bash
redis-cli -u $REDIS_URL ping
```

### High proxy costs

Check which domains are using residential proxy:

```python
from price_radar.application.proxy_resolver import ProxyResolver
resolver = ProxyResolver(proxy_url="...", redis_client=redis)
# Check a specific domain
print(resolver.get_tier_info("example.com"))
```
