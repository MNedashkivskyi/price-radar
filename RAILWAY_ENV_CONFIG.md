# Railway Environment Configuration

## Frontend Environment Variables

### Required Configuration

To fix "API Status: unavailable" in Railway frontend deployment:

1. **Go to Railway Dashboard** → Frontend Service → **Variables**

2. **Add the following environment variable:**
   ```
   Key: NEXT_PUBLIC_API_URL
   Value: https://price-radar-production.up.railway.app
   ```

   Replace `price-radar-production.up.railway.app` with your actual backend Railway URL.

3. **Important Notes:**
   - The variable MUST start with `NEXT_PUBLIC_` to be available in the browser
   - Use `https://` (not `http://`) for production
   - Do NOT include `/api` or trailing slashes
   - The URL should be your backend service URL (where FastAPI is running)

### How to Find Your Backend URL

1. Go to Railway Dashboard → Backend Service
2. Look for "Domains" section
3. Copy the generated Railway domain (e.g., `price-radar-production.up.railway.app`)
4. Use this as `NEXT_PUBLIC_API_URL=https://price-radar-production.up.railway.app`

### After Setting the Variable

1. Railway will automatically redeploy the frontend
2. The Next.js build will include the environment variable
3. Frontend will connect to the correct backend API
4. Health check will show "API Status: healthy"

## Backend Environment Variables

Backend should already have these configured:

```
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
CELERY_BROKER_URL=redis://...
CELERY_RESULT_BACKEND=redis://...
SHOPIFY_API_KEY=...
SHOPIFY_API_SECRET=...
SHOPIFY_APP_URL=https://price-radar-production.up.railway.app
SHOPIFY_SCOPES=read_products,write_products,read_orders
SHOPIFY_API_VERSION=2024-01
SECRET_KEY=...
ENCRYPTION_KEY=...
```

## Local Development

For local development, the frontend uses `.env.local`:

```bash
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

This file is already created and ignored by git.

## CORS Configuration

If you still get API errors after setting the environment variable, ensure the backend has CORS configured to allow your frontend domain:

```python
# backend/src/price_radar/api/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local development
        "https://your-frontend.up.railway.app",  # Railway frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Check your backend `main.py` for the CORS configuration.
