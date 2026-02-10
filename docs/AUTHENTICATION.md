# Authentication & Session Management

## Overview

Price Radar uses a two-step authentication flow:
1. **Shopify OAuth 2.0** for initial app installation and access token exchange
2. **JWT (JSON Web Tokens)** for frontend session management

This design provides:
- Secure OAuth flow following Shopify's best practices
- Encrypted access token storage at rest (AES via Fernet)
- Stateless JWT sessions for scalability
- Easy integration with frontend dashboard

## OAuth Flow

### 1. Installation Endpoint

**Endpoint:** `GET /api/shopify/install?shop={shop_domain}`

Initiates the Shopify app installation by redirecting the merchant to Shopify's consent screen.

**Parameters:**
- `shop`: Shop domain (e.g., `my-store` or `my-store.myshopify.com`)

**Flow:**
1. Normalizes shop domain to full `.myshopify.com` format
2. Generates authorization URL with required scopes
3. Redirects merchant to Shopify OAuth consent page

**Example:**
```
GET /api/shopify/install?shop=my-store
→ Redirects to: https://my-store.myshopify.com/admin/oauth/authorize?client_id=...&scope=...
```

### 2. OAuth Callback Endpoint

**Endpoint:** `GET /api/shopify/callback`

Handles the OAuth callback after the merchant authorizes the app.

**Parameters:**
- `shop`: Shop domain
- `code`: Authorization code from Shopify
- `hmac`: HMAC signature for security verification
- `state`: (Optional) CSRF protection parameter

**Flow:**
1. Verifies HMAC signature to ensure request is from Shopify
2. Exchanges authorization code for access token
3. Encrypts access token using Fernet (AES-128-CBC)
4. Saves shop record in database
5. Generates JWT session token
6. Redirects to frontend dashboard with JWT token

**Example:**
```
GET /api/shopify/callback?shop=my-store.myshopify.com&code=abc123&hmac=...
→ Redirects to: http://localhost:3000/dashboard?token={jwt_token}
```

## JWT Session Management

### Token Structure

JWT tokens contain the following claims:

```json
{
  "shop_id": 123,
  "shop_domain": "my-store.myshopify.com",
  "iat": 1234567890,
  "exp": 1234654290,
  "type": "session"
}
```

**Claims:**
- `shop_id`: Database ID of the shop
- `shop_domain`: Shop's Shopify domain
- `iat`: Issued at timestamp
- `exp`: Expiration timestamp (default: 24 hours)
- `type`: Token type (always "session")

### Configuration

JWT settings are configured via environment variables:

```env
JWT_SECRET_KEY=your-secret-key-here  # IMPORTANT: Use strong random value in production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
```

**Security Note:** The JWT secret key should be:
- At least 32 bytes long
- Randomly generated
- Never committed to version control
- Rotated periodically in production

### Generating Tokens

```python
from price_radar.application.jwt_service import JWTService

jwt_service = JWTService()
token = jwt_service.create_session_token(shop_id=123, shop_domain="my-store.myshopify.com")
```

### Verifying Tokens

```python
jwt_service = JWTService()
try:
    payload = jwt_service.verify_token(token)
    shop_id = payload["shop_id"]
except jwt.InvalidTokenError as e:
    # Token is invalid or expired
    pass
```

## Protected API Endpoints

### Using Authentication Middleware

To protect an API endpoint, use the `get_current_shop_id` dependency:

```python
from fastapi import APIRouter, Depends
from price_radar.api.middleware import get_current_shop_id

router = APIRouter()

@router.get("/protected")
async def protected_endpoint(
    shop_id: int = Depends(get_current_shop_id)
) -> dict:
    # shop_id is automatically extracted from JWT
    return {"shop_id": shop_id, "message": "Access granted"}
```

### Making Authenticated Requests

Frontend applications should include the JWT token in the Authorization header:

```http
GET /api/protected HTTP/1.1
Host: api.priceradar.com
Authorization: Bearer {jwt_token}
```

### Optional Authentication

For endpoints that support both authenticated and unauthenticated access:

```python
from price_radar.api.middleware import get_optional_shop_id

@router.get("/public-or-private")
async def flexible_endpoint(
    shop_id: int | None = Depends(get_optional_shop_id)
) -> dict:
    if shop_id:
        return {"message": f"Hello shop {shop_id}"}
    else:
        return {"message": "Hello anonymous user"}
```

## Authentication Endpoints

### Get Current Shop

**Endpoint:** `GET /api/auth/me`

Returns information about the currently authenticated shop.

**Headers:**
```
Authorization: Bearer {jwt_token}
```

**Response:**
```json
{
  "id": 123,
  "shopify_domain": "my-store.myshopify.com",
  "plan": "free",
  "status": "active",
  "created_at": "2026-02-10T12:00:00"
}
```

### Refresh Token

**Endpoint:** `POST /api/auth/refresh`

Generates a new JWT token for the current session.

**Headers:**
```
Authorization: Bearer {jwt_token}
```

**Response:**
```json
{
  "access_token": "{new_jwt_token}",
  "token_type": "bearer"
}
```

## Security Features

### Token Encryption at Rest

Shopify access tokens are encrypted before storage using Fernet (AES-128-CBC):

```python
from cryptography.fernet import Fernet

# Generate encryption key (done once at startup)
encryption_key = Fernet.generate_key()
cipher = Fernet(encryption_key)

# Encrypt token before storage
encrypted_token = cipher.encrypt(access_token.encode())

# Decrypt when needed
decrypted_token = cipher.decrypt(encrypted_token)
```

### HMAC Verification

All OAuth callbacks verify the HMAC signature to ensure requests originate from Shopify:

```python
def verify_hmac(query_params: dict[str, str]) -> bool:
    hmac_value = query_params.get("hmac", "")
    params = {k: v for k, v in query_params.items() if k != "hmac"}

    # Sort and encode parameters
    query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    # Compute HMAC-SHA256
    computed_hmac = hmac.new(
        secret_key.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_hmac, hmac_value)
```

### JWT Expiration

Tokens automatically expire after the configured time period (default: 24 hours). Expired tokens are rejected with a 401 Unauthorized error.

### CORS Configuration

The API is configured to accept requests from the frontend origin:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Error Handling

### Authentication Errors

**401 Unauthorized:** Missing or invalid token
```json
{
  "detail": "Missing authentication token"
}
```

**401 Unauthorized:** Expired token
```json
{
  "detail": "Invalid authentication token: Token has expired"
}
```

**403 Forbidden:** Invalid HMAC signature (OAuth callback)
```json
{
  "detail": "Invalid HMAC signature"
}
```

**404 Not Found:** Shop not found
```json
{
  "detail": "Shop not found"
}
```

## Frontend Integration

### Storing the JWT Token

After successful OAuth, the frontend receives the JWT as a query parameter:

```javascript
// Extract token from URL
const params = new URLSearchParams(window.location.search);
const token = params.get('token');

// Store in localStorage or sessionStorage
localStorage.setItem('auth_token', token);

// Clean up URL
window.history.replaceState({}, document.title, '/dashboard');
```

### Making API Calls

```javascript
// Fetch with authentication
const response = await fetch('http://localhost:8000/api/auth/me', {
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
  }
});

const shop = await response.json();
```

### Token Refresh

```javascript
async function refreshToken() {
  const response = await fetch('http://localhost:8000/api/auth/refresh', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
    }
  });

  const data = await response.json();
  localStorage.setItem('auth_token', data.access_token);
  return data.access_token;
}
```

### Handling Token Expiration

```javascript
async function apiCall(url, options = {}) {
  let response = await fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
    }
  });

  // If token expired, try to refresh
  if (response.status === 401) {
    const newToken = await refreshToken();
    response = await fetch(url, {
      ...options,
      headers: {
        ...options.headers,
        'Authorization': `Bearer ${newToken}`
      }
    });
  }

  return response;
}
```

## Environment Variables

Required environment variables for authentication:

```env
# Shopify OAuth
SHOPIFY_API_KEY=your-api-key
SHOPIFY_API_SECRET=your-api-secret
SHOPIFY_APP_URL=http://localhost:8000
SHOPIFY_SCOPES=read_products,write_products,read_orders

# JWT
JWT_SECRET_KEY=your-32-byte-or-longer-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Frontend
FRONTEND_URL=http://localhost:3000
```

## Testing Authentication

### Testing JWT Creation/Verification

```python
from price_radar.application.jwt_service import JWTService

jwt_service = JWTService()
jwt_service.secret_key = "test-secret-key"

# Create token
token = jwt_service.create_session_token(123, "test-shop.myshopify.com")

# Verify token
payload = jwt_service.verify_token(token)
assert payload["shop_id"] == 123
```

### Testing Protected Endpoints

```python
from fastapi.testclient import TestClient

def test_protected_endpoint():
    # Create valid JWT
    jwt_service = JWTService()
    token = jwt_service.create_session_token(123, "test-shop.myshopify.com")

    # Make request with token
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
```

## Best Practices

1. **Always use HTTPS in production** - JWT tokens should never be transmitted over unsecured connections
2. **Rotate JWT secrets regularly** - Update the JWT_SECRET_KEY periodically
3. **Use strong encryption keys** - Generate keys with at least 256 bits of entropy
4. **Implement token refresh** - Allow users to refresh tokens before expiration
5. **Log authentication events** - Track login/logout for security monitoring
6. **Rate limit authentication endpoints** - Prevent brute force attacks
7. **Validate token claims** - Always verify shop_id and expiration
8. **Handle token expiration gracefully** - Redirect to login or refresh automatically
9. **Store tokens securely** - Use httpOnly cookies or secure storage
10. **Never log tokens or secrets** - Ensure sensitive data isn't logged

## Troubleshooting

### "Invalid HMAC signature" error
- Verify SHOPIFY_API_SECRET is correct
- Ensure query parameters aren't being modified
- Check for URL encoding issues

### "Token has expired" error
- Token has been valid for more than JWT_EXPIRATION_HOURS
- User needs to reauthenticate or refresh token

### "Missing authentication token" error
- Authorization header not included in request
- Token not in correct Bearer format
- Check CORS settings if from browser

### "Shop not found" error
- Shop was deleted from database
- shop_id in JWT doesn't match database
- Database migration needed
