># Shopify Integration Guide

This document explains how the Shopify integration works in Price Radar.

## Overview

Price Radar integrates with Shopify via OAuth 2.0 to access store data including products and orders. The integration follows Shopify's best practices for app development.

## Architecture

### Components

1. **Domain Layer** (`domain/shopify.py`)
   - `ShopifyStore`: Domain model representing a Shopify store
   - Business logic for scope checking and validation

2. **Application Layer** (`application/shopify_service.py`)
   - `ShopifyService`: Handles OAuth flow and API requests
   - Token encryption/decryption
   - HMAC verification
   - Database operations

3. **Infrastructure Layer** (`infrastructure/models.py`)
   - `ShopifyStoreModel`: SQLAlchemy model for database storage
   - Stores encrypted access tokens

4. **API Layer** (`api/shopify.py`)
   - REST endpoints for OAuth flow
   - Store management endpoints
   - Product and order access endpoints

## OAuth Flow

### 1. Installation Request

```
GET /api/shopify/install?shop={shop_domain}
```

**Process:**
1. User visits installation URL
2. System generates Shopify OAuth URL with required scopes
3. Redirects user to Shopify authorization page

### 2. User Authorization

User reviews requested permissions and clicks "Install app" on Shopify.

### 3. OAuth Callback

```
GET /api/shopify/callback?shop={shop}&code={code}&hmac={hmac}&state={state}
```

**Process:**
1. Shopify redirects back with authorization code
2. System verifies HMAC signature
3. Exchanges code for access token
4. Encrypts and stores access token in database
5. Returns success page to user

### 4. Token Storage

Access tokens are:
- Encrypted using Fernet (symmetric encryption)
- Stored in PostgreSQL
- Associated with shop domain
- Marked with installation timestamp

## API Endpoints

### Installation

#### Start Installation
```http
GET /api/shopify/install?shop={shop_domain}
```

Redirects to Shopify OAuth authorization page.

**Query Parameters:**
- `shop` (required): Shop domain (e.g., "myshop" or "myshop.myshopify.com")

**Response:**
- `307 Temporary Redirect` to Shopify

#### OAuth Callback
```http
GET /api/shopify/callback?shop={shop}&code={code}&hmac={hmac}&state={state}
```

Handles OAuth callback from Shopify.

**Query Parameters:**
- `shop` (required): Shop domain
- `code` (required): Authorization code
- `hmac` (required): HMAC signature for verification
- `state` (optional): State parameter for CSRF protection

**Response:**
- `200 OK`: HTML success page
- `403 Forbidden`: Invalid HMAC
- `500 Internal Server Error`: Installation failed

### Store Management

#### Get Store Info
```http
GET /api/shopify/stores/{shop_domain}
```

Retrieve information about an installed store.

**Response:**
```json
{
  "shop_domain": "myshop.myshopify.com",
  "scopes": "read_products,write_products,read_orders",
  "is_active": true,
  "installed_at": "2026-02-10T14:00:00"
}
```

### Data Access

#### Get Products
```http
GET /api/shopify/stores/{shop_domain}/products?limit=50
```

Fetch products from Shopify store.

**Query Parameters:**
- `limit` (optional): Number of products (1-250, default: 50)

**Response:**
```json
{
  "products": [
    {
      "id": 123456789,
      "title": "Product Name",
      "vendor": "Vendor Name",
      "product_type": "Type",
      "variants": [...]
    }
  ]
}
```

#### Get Orders
```http
GET /api/shopify/stores/{shop_domain}/orders?limit=50
```

Fetch orders from Shopify store.

**Query Parameters:**
- `limit` (optional): Number of orders (1-250, default: 50)

**Response:**
```json
{
  "orders": [
    {
      "id": 123456789,
      "email": "customer@example.com",
      "total_price": "100.00",
      "line_items": [...]
    }
  ]
}
```

## Security

### Token Encryption

Access tokens are encrypted before storage using Fernet symmetric encryption:

```python
# Encryption
encrypted_token = cipher.encrypt(token.encode()).decode()

# Decryption
token = cipher.decrypt(encrypted_token.encode()).decode()
```

### HMAC Verification

All OAuth callbacks are verified using HMAC-SHA256:

```python
# Compute HMAC
computed_hmac = hmac.new(
    api_secret.encode("utf-8"),
    encoded_params.encode("utf-8"),
    hashlib.sha256,
).hexdigest()

# Compare with provided HMAC
is_valid = hmac.compare_digest(computed_hmac, provided_hmac)
```

### Access Control

- Access tokens are never exposed in API responses
- Each store's token is isolated
- Tokens can be revoked by uninstalling the app

## Configuration

### Environment Variables

Required in `.env`:

```bash
SHOPIFY_API_KEY=your_api_key
SHOPIFY_API_SECRET=your_api_secret
SHOPIFY_APP_URL=http://localhost:8000
SHOPIFY_SCOPES=read_products,write_products,read_orders
SHOPIFY_API_VERSION=2024-01
```

### Scopes

Current scopes requested:
- `read_products`: View product data
- `write_products`: Modify product data
- `read_orders`: View order data

To add more scopes, update `SHOPIFY_SCOPES` and reconfigure in Partner Dashboard.

## Testing

### Manual Testing

1. **Start the backend:**
   ```bash
   cd backend
   poetry run alembic upgrade head
   poetry run uvicorn price_radar.api.main:app --reload
   ```

2. **Generate installation URL:**
   ```bash
   curl "http://localhost:8000/api/shopify/install?shop=your-dev-store"
   ```

3. **Visit the returned URL in browser**

4. **Complete OAuth flow**

5. **Verify in database:**
   ```sql
   SELECT shop_domain, scopes, installed_at FROM shopify_stores;
   ```

6. **Test API access:**
   ```bash
   curl "http://localhost:8000/api/shopify/stores/your-dev-store.myshopify.com/products"
   ```

### Automated Tests

Run tests with pytest:

```bash
cd backend
poetry run pytest tests/test_shopify.py -v
```

## Database Schema

### shopify_stores Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| shop_domain | VARCHAR(255) | Unique shop domain |
| access_token | TEXT | Encrypted access token |
| scopes | VARCHAR(500) | Granted scopes (comma-separated) |
| is_active | BOOLEAN | Installation status |
| installed_at | DATETIME | Installation timestamp |
| uninstalled_at | DATETIME | Uninstallation timestamp (nullable) |

## Error Handling

### Common Errors

**403 Forbidden - Invalid HMAC**
- HMAC signature verification failed
- Possible security issue or replay attack
- Check API secret configuration

**404 Not Found - Store not found**
- Store hasn't installed the app yet
- Check shop domain format
- Verify database connection

**500 Internal Server Error - Installation failed**
- Token exchange failed
- Database error
- Check logs for details

### Debugging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check logs for:
- OAuth callback parameters
- HMAC verification details
- API request/response data
- Database operations

## Rate Limits

Shopify enforces API rate limits:
- **REST Admin API**: 2 requests/second
- **GraphQL Admin API**: 1000 points/60 seconds

The service doesn't currently implement rate limiting. For production:
- Add rate limit tracking
- Implement exponential backoff
- Use bulk operations where possible

## Webhooks

To receive real-time updates from Shopify, implement webhooks:

### Recommended Webhooks

- `app/uninstalled`: Track when app is uninstalled
- `products/create`: Product created
- `products/update`: Product updated
- `products/delete`: Product deleted
- `orders/create`: Order created

### Implementation (TODO)

```python
@router.post("/webhooks/app-uninstalled")
async def handle_uninstall(request: Request):
    # Verify webhook
    # Mark store as inactive
    pass
```

## Best Practices

1. **Token Security**
   - Never log access tokens
   - Use encryption at rest
   - Rotate encryption keys regularly

2. **API Requests**
   - Cache responses when appropriate
   - Handle rate limits gracefully
   - Use bulk endpoints for large operations

3. **Error Handling**
   - Log all OAuth failures
   - Provide clear error messages
   - Implement retry logic for transient errors

4. **Testing**
   - Test with development stores
   - Verify all scopes work correctly
   - Test uninstall/reinstall flow

5. **Monitoring**
   - Track OAuth success/failure rates
   - Monitor API error rates
   - Alert on unexpected failures

## Troubleshooting

### Installation URL doesn't work
- Verify `SHOPIFY_APP_URL` matches your actual URL
- Check redirect URL in Partner Dashboard
- Ensure shop domain is correct

### HMAC verification fails
- Check `SHOPIFY_API_SECRET` is correct
- Verify no modifications to query parameters
- Check for URL encoding issues

### Token exchange fails
- Verify `SHOPIFY_API_KEY` and `SHOPIFY_API_SECRET`
- Check code hasn't been used already (codes are single-use)
- Ensure callback URL matches Partner Dashboard

### API requests return 401
- Check access token isn't expired
- Verify token has required scopes
- Ensure shop hasn't uninstalled app

## Next Steps

After basic integration:

1. **Implement Webhooks**
   - Receive real-time updates
   - Handle app uninstallation
   - Sync data automatically

2. **Add GraphQL Support**
   - More efficient data fetching
   - Better performance for complex queries
   - Access to newer features

3. **Implement Pagination**
   - Handle large datasets
   - Cursor-based pagination
   - Background sync jobs

4. **Add Caching**
   - Cache product/order data
   - Reduce API calls
   - Improve response times

5. **Build Admin UI**
   - App management dashboard
   - Configuration interface
   - Analytics and reporting

## Resources

- [Shopify App Development](https://shopify.dev/docs/apps)
- [OAuth Documentation](https://shopify.dev/docs/apps/auth/oauth)
- [Admin API Reference](https://shopify.dev/docs/api/admin-rest)
- [Rate Limits](https://shopify.dev/docs/api/usage/rate-limits)
- [Webhooks](https://shopify.dev/docs/apps/webhooks)
