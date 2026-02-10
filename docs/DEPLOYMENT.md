# Deployment Guide - Staging Environment

## Overview

This guide covers deploying Price Radar to a staging environment using Railway (recommended) or Render. The stack includes:
- Backend API (FastAPI + Uvicorn)
- PostgreSQL Database
- Redis Cache
- Celery Worker
- Celery Beat (scheduler)
- Frontend (Next.js)

## Option 1: Railway Deployment (Recommended)

Railway provides the simplest deployment experience with automatic HTTPS, custom domains, and integrated databases.

### Prerequisites

1. Create a Railway account at https://railway.app
2. Install Railway CLI (optional):
   ```bash
   npm install -g @railway/cli
   railway login
   ```

### Step 1: Create New Project

1. Go to https://railway.app/new
2. Click "New Project"
3. Select "Empty Project"
4. Name it `price-radar-staging`

### Step 2: Provision Database Services

#### PostgreSQL Database

1. In your Railway project, click "+ New"
2. Select "Database" → "PostgreSQL"
3. Railway will automatically provision and configure the database
4. Note the connection string from the "Connect" tab (you won't need to copy it manually)

#### Redis Cache

1. Click "+ New" again
2. Select "Database" → "Redis"
3. Railway will provision Redis automatically

### Step 3: Deploy Backend API

1. In your Railway project, click "+ New"
2. Select "GitHub Repo"
3. Connect your `price-radar` repository
4. Select the `master` branch
5. Railway will detect the Dockerfile and build automatically

#### Configure Backend Environment Variables

Click on the backend service → "Variables" tab and add:

```env
# Database (automatically set by Railway if using their PostgreSQL)
DATABASE_URL=${{Postgres.DATABASE_URL}}

# Redis (automatically set by Railway if using their Redis)
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}/0
CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}/1

# Application
APP_NAME=Price Radar API
DEBUG=false

# Shopify OAuth
SHOPIFY_API_KEY=your-shopify-api-key
SHOPIFY_API_SECRET=your-shopify-api-secret
SHOPIFY_APP_URL=https://your-app.railway.app
SHOPIFY_SCOPES=read_products,write_products,read_orders
SHOPIFY_API_VERSION=2024-01

# JWT Authentication
JWT_SECRET_KEY=<generate-secure-32-byte-key>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Frontend
FRONTEND_URL=https://your-frontend.railway.app

# Port (Railway sets this automatically)
PORT=8000
```

**Generate JWT Secret:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Configure Custom Domain (Optional)

1. Go to backend service → "Settings"
2. Scroll to "Networking" → "Public Networking"
3. Click "Generate Domain" for a free `.railway.app` domain
4. Or click "Custom Domain" to add your own domain

### Step 4: Deploy Celery Worker

1. Click "+ New" → "GitHub Repo"
2. Select the same `price-radar` repository
3. After it's created, go to "Settings"
4. Under "Build", set:
   - **Dockerfile Path**: `backend/Dockerfile.celery`
5. Under "Deploy", set:
   - **Start Command**: `celery -A price_radar.infrastructure.celery_app worker --loglevel=info`

#### Configure Celery Worker Environment

Add the same environment variables as the backend (copy from backend service).

### Step 5: Deploy Celery Beat (Scheduler)

1. Click "+ New" → "GitHub Repo"
2. Select the same `price-radar` repository
3. Go to "Settings"
4. Under "Build", set:
   - **Dockerfile Path**: `backend/Dockerfile.celery`
5. Under "Deploy", set:
   - **Start Command**: `celery -A price_radar.infrastructure.celery_app beat --loglevel=info`

#### Configure Celery Beat Environment

Add the same environment variables as the backend.

### Step 6: Deploy Frontend (Next.js)

1. Click "+ New" → "GitHub Repo"
2. Select the `price-radar` repository
3. Go to "Settings"
4. Under "Build", set:
   - **Root Directory**: `frontend`
   - **Build Command**: `npm install && npm run build`
   - **Start Command**: `npm start`

#### Configure Frontend Environment

```env
NEXT_PUBLIC_API_URL=https://your-backend.railway.app
```

### Step 7: Configure Shopify App URLs

1. Go to Shopify Partner Dashboard
2. Select your app
3. Update these URLs:
   - **App URL**: `https://your-backend.railway.app/api/shopify/install`
   - **Allowed redirection URL(s)**: `https://your-backend.railway.app/api/shopify/callback`

### Step 8: Test the Deployment

1. Visit your backend URL: `https://your-backend.railway.app/health`
   - Should return: `{"status": "healthy"}`

2. Test OAuth flow:
   - Visit: `https://your-backend.railway.app/api/shopify/install?shop=your-dev-store`
   - Complete Shopify OAuth
   - Should redirect to frontend with JWT token

3. Check Celery worker logs in Railway dashboard

---

## Option 2: Render Deployment

### Prerequisites

1. Create account at https://render.com
2. Connect your GitHub repository

### Step 1: Create PostgreSQL Database

1. From Render dashboard, click "New +"
2. Select "PostgreSQL"
3. Configure:
   - **Name**: `price-radar-db`
   - **Database**: `price_radar`
   - **User**: `price_radar_user`
   - **Region**: Choose closest to you
   - **Plan**: Free tier for staging
4. Click "Create Database"
5. Copy the "Internal Database URL" from the database page

### Step 2: Create Redis Instance

1. Click "New +" → "Redis"
2. Configure:
   - **Name**: `price-radar-redis`
   - **Plan**: Free tier
3. Click "Create Redis"
4. Copy the "Internal Redis URL"

### Step 3: Deploy Backend Web Service

1. Click "New +" → "Web Service"
2. Connect your GitHub repository
3. Configure:
   - **Name**: `price-radar-api`
   - **Region**: Same as database
   - **Branch**: `master`
   - **Root Directory**: `backend`
   - **Runtime**: `Docker`
   - **Dockerfile Path**: `Dockerfile`
   - **Instance Type**: Free tier

#### Environment Variables

Add under "Environment":

```env
DATABASE_URL=<internal-database-url-from-step-1>
REDIS_URL=<internal-redis-url-from-step-2>
CELERY_BROKER_URL=<redis-url>/0
CELERY_RESULT_BACKEND=<redis-url>/1
APP_NAME=Price Radar API
DEBUG=false
SHOPIFY_API_KEY=your-shopify-api-key
SHOPIFY_API_SECRET=your-shopify-api-secret
SHOPIFY_APP_URL=https://your-app.onrender.com
SHOPIFY_SCOPES=read_products,write_products,read_orders
SHOPIFY_API_VERSION=2024-01
JWT_SECRET_KEY=<generate-secure-key>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
FRONTEND_URL=https://your-frontend.onrender.com
PORT=8000
```

4. Click "Create Web Service"

### Step 4: Deploy Celery Worker

1. Click "New +" → "Background Worker"
2. Connect your repository
3. Configure:
   - **Name**: `price-radar-worker`
   - **Root Directory**: `backend`
   - **Runtime**: `Docker`
   - **Dockerfile Path**: `Dockerfile.celery`
   - **Start Command**: `celery -A price_radar.infrastructure.celery_app worker --loglevel=info`

Add the same environment variables as the backend.

### Step 5: Deploy Celery Beat

1. Click "New +" → "Background Worker"
2. Configure:
   - **Name**: `price-radar-beat`
   - **Root Directory**: `backend`
   - **Runtime**: `Docker`
   - **Dockerfile Path**: `Dockerfile.celery`
   - **Start Command**: `celery -A price_radar.infrastructure.celery_app beat --loglevel=info`

Add the same environment variables.

### Step 6: Deploy Frontend

1. Click "New +" → "Static Site" (or "Web Service" for SSR)
2. Configure:
   - **Name**: `price-radar-frontend`
   - **Root Directory**: `frontend`
   - **Build Command**: `npm install && npm run build`
   - **Publish Directory**: `.next` (for Next.js)

Environment:
```env
NEXT_PUBLIC_API_URL=https://price-radar-api.onrender.com
```

---

## Post-Deployment Checklist

### 1. Verify All Services Are Running

- [ ] Backend API is accessible via HTTPS
- [ ] Database connection is working
- [ ] Redis is connected
- [ ] Celery worker is processing tasks
- [ ] Celery beat is scheduling tasks
- [ ] Frontend is accessible

### 2. Run Database Migrations

If migrations didn't run automatically:

**Railway:**
```bash
railway run alembic upgrade head
```

**Render:**
Go to your web service → "Shell" tab
```bash
alembic upgrade head
```

### 3. Test Health Endpoints

```bash
# Backend health
curl https://your-backend-url.com/health

# Expected: {"status":"healthy"}
```

### 4. Test OAuth Flow

1. Visit: `https://your-backend-url.com/api/shopify/install?shop=your-dev-store`
2. Complete Shopify authorization
3. Verify redirect to frontend with JWT token
4. Check that shop record was created in database

### 5. Test Authentication

```bash
# Get JWT token from OAuth flow, then test:
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  https://your-backend-url.com/api/auth/me
```

### 6. Monitor Logs

**Railway:**
- Click on each service to view live logs
- Check for errors or warnings

**Render:**
- Go to each service → "Logs" tab
- Monitor for errors

### 7. Set up Custom Domain (Optional)

**Railway:**
1. Go to service → Settings → Networking
2. Add custom domain
3. Update DNS records as instructed

**Render:**
1. Go to service → Settings → Custom Domain
2. Add your domain
3. Update DNS with CNAME record

---

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection string | `redis://host:6379/0` |
| `SHOPIFY_API_KEY` | From Shopify Partner Dashboard | `abc123...` |
| `SHOPIFY_API_SECRET` | From Shopify Partner Dashboard | `xyz789...` |
| `SHOPIFY_APP_URL` | Your deployed backend URL | `https://api.yourapp.com` |
| `JWT_SECRET_KEY` | 32+ byte random string | Generate with Python command |
| `FRONTEND_URL` | Your deployed frontend URL | `https://yourapp.com` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `false` |
| `JWT_EXPIRATION_HOURS` | JWT token lifetime | `24` |
| `SHOPIFY_SCOPES` | Shopify API scopes | `read_products,write_products,read_orders` |
| `PORT` | Application port | `8000` |

---

## Troubleshooting

### Backend Won't Start

**Check logs for:**
- Database connection errors
- Missing environment variables
- Migration failures

**Solutions:**
```bash
# Verify DATABASE_URL is set correctly
echo $DATABASE_URL

# Run migrations manually
alembic upgrade head

# Check if PostgreSQL is accessible
pg_isready -h hostname -p 5432
```

### Celery Worker Not Processing Tasks

**Check:**
- Redis connection (CELERY_BROKER_URL)
- Worker logs for errors
- Task definition in code

**Test Redis connection:**
```python
import redis
r = redis.from_url("your-redis-url")
r.ping()  # Should return True
```

### OAuth Callback Fails

**Common issues:**
- Shopify App URLs don't match deployed URLs
- HMAC verification fails (wrong SHOPIFY_API_SECRET)
- Database not accessible

**Verify:**
1. Shopify Partner Dashboard URLs match deployment
2. All environment variables are set
3. Backend logs for specific error

### CORS Errors from Frontend

**Update CORS settings** in `backend/src/price_radar/api/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local dev
        "https://your-frontend.railway.app",  # Staging
        "https://yourapp.com",  # Production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Database Connection Pool Exhausted

Add connection pooling settings to DATABASE_URL:
```
postgresql://user:pass@host:5432/db?pool_size=10&max_overflow=20
```

---

## Monitoring & Maintenance

### Health Checks

Set up monitoring for:
- Backend: `GET /health`
- Database connectivity
- Redis connectivity
- Celery worker status

### Logging

**Railway:**
- Built-in log aggregation
- Real-time log streaming

**Render:**
- Log retention based on plan
- Export logs if needed

### Backups

**Database Backups:**

**Railway:**
- Automatic daily backups on paid plans
- Manual backups via Railway CLI

**Render:**
- Automatic backups on paid plans
- Export via pg_dump:
  ```bash
  pg_dump $DATABASE_URL > backup.sql
  ```

### Scaling

**Railway:**
- Horizontal scaling: Increase replicas in service settings
- Vertical scaling: Upgrade instance size

**Render:**
- Upgrade to paid plan for auto-scaling
- Manually scale instances

---

## Security Best Practices

1. **Use Environment Variables**: Never hardcode secrets
2. **Strong JWT Secret**: Generate 32+ byte random keys
3. **HTTPS Only**: Enforce HTTPS in production
4. **Database Security**: Use connection pooling and SSL
5. **Rate Limiting**: Add rate limiting to API endpoints
6. **Rotate Secrets**: Periodically update JWT and API secrets
7. **Monitor Logs**: Watch for suspicious activity
8. **Firewall Rules**: Restrict database access to application only

---

## Next Steps After Deployment

1. **Set up monitoring**: Use Railway metrics or external services (Sentry, DataDog)
2. **Configure alerts**: Get notified of downtime or errors
3. **Set up CI/CD**: Automate deployments on push to master
4. **Add rate limiting**: Protect against abuse
5. **Enable database backups**: Ensure data safety
6. **Document runbook**: Create operational procedures
7. **Load testing**: Test performance under load
8. **Security audit**: Run security scans

---

## Cost Estimates

### Railway (Recommended)

- **Hobby Plan**: $5/month (includes $5 credit)
  - PostgreSQL: Included
  - Redis: Included
  - 3-4 services: Covered by credit
- **Estimated Total**: $5-10/month for staging

### Render

- **Free Tier**:
  - PostgreSQL: Free (90 days, then $7/month)
  - Redis: Free (expires after 90 days)
  - Web Services: Free (sleeps after inactivity)
  - Background Workers: $7/month each
- **Estimated Total**: $0-21/month (with limitations)

---

## Support

- **Railway**: https://railway.app/help
- **Render**: https://render.com/docs
- **Project Issues**: https://github.com/MNedashkivskyi/price-radar/issues
