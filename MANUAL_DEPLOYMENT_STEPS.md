# Manual Deployment Steps for Staging Environment

## What You Need to Do

Since I cannot access external platforms like Railway or Render, you'll need to complete the deployment manually following these steps. All configuration files have been created for you.

---

## Prerequisites

Before you begin, ensure you have:

1. ✅ **Shopify Partner Account**
   - Create at: https://partners.shopify.com
   - Create a new app in the Partner Dashboard
   - Note your API Key and API Secret

2. ✅ **Shopify Development Store**
   - Create a development store in Partner Dashboard
   - This is where you'll test the app installation

3. ✅ **Railway or Render Account**
   - Railway (Recommended): https://railway.app
   - Render (Alternative): https://render.com

---

## Step-by-Step Deployment

### Step 1: Generate JWT Secret

Run this command to generate a secure JWT secret:

```bash
python scripts/generate_secrets.py
```

Or manually:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Save this secret** - you'll need it for environment variables.

---

### Step 2: Choose Your Hosting Platform

#### Option A: Railway (Recommended - Simpler)

1. **Create Railway Account**
   - Go to https://railway.app
   - Sign up with GitHub

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Connect the `price-radar` repository
   - Select `master` branch

3. **Add PostgreSQL Database**
   - In your project, click "+ New"
   - Select "Database" → "PostgreSQL"
   - Railway will provision it automatically
   - Note: DATABASE_URL will be available as `${{Postgres.DATABASE_URL}}`

4. **Add Redis**
   - Click "+ New"
   - Select "Database" → "Redis"
   - Railway will provision it automatically
   - Note: REDIS_URL will be available as `${{Redis.REDIS_URL}}`

5. **Deploy Backend API**
   - Your GitHub repo should already be added
   - Railway will detect the `Dockerfile` automatically
   - Go to service → "Variables" tab
   - Add all environment variables (see list below)
   - Deploy will start automatically

6. **Deploy Celery Worker**
   - Click "+ New" → "GitHub Repo"
   - Select the same repository
   - Go to "Settings" → "Build"
   - Set **Dockerfile Path**: `backend/Dockerfile.celery`
   - Go to "Deploy"
   - Set **Start Command**: `celery -A price_radar.infrastructure.celery_app worker --loglevel=info`
   - Add same environment variables as backend

7. **Deploy Celery Beat**
   - Click "+ New" → "GitHub Repo"
   - Select the same repository
   - Go to "Settings" → "Build"
   - Set **Dockerfile Path**: `backend/Dockerfile.celery`
   - Go to "Deploy"
   - Set **Start Command**: `celery -A price_radar.infrastructure.celery_app beat --loglevel=info`
   - Add same environment variables

#### Option B: Render (Alternative)

Follow the detailed steps in `docs/DEPLOYMENT.md` under "Option 2: Render Deployment".

---

### Step 3: Configure Environment Variables

Add these environment variables to your Backend, Celery Worker, and Celery Beat services:

**For Railway (use Railway Variables):**

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}/1
CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}/2
APP_NAME=Price Radar API
DEBUG=false
SHOPIFY_API_KEY=<YOUR_SHOPIFY_API_KEY>
SHOPIFY_API_SECRET=<YOUR_SHOPIFY_API_SECRET>
SHOPIFY_APP_URL=<YOUR_RAILWAY_BACKEND_URL>
SHOPIFY_SCOPES=read_products,write_products,read_orders
SHOPIFY_API_VERSION=2024-01
JWT_SECRET_KEY=<GENERATED_SECRET_FROM_STEP_1>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
FRONTEND_URL=<YOUR_FRONTEND_URL_OR_LOCALHOST>
```

**Replace these values:**
- `<YOUR_SHOPIFY_API_KEY>` - From Shopify Partner Dashboard
- `<YOUR_SHOPIFY_API_SECRET>` - From Shopify Partner Dashboard
- `<YOUR_RAILWAY_BACKEND_URL>` - Your Railway backend URL (e.g., https://price-radar-backend.railway.app)
- `<GENERATED_SECRET_FROM_STEP_1>` - The JWT secret you generated
- `<YOUR_FRONTEND_URL_OR_LOCALHOST>` - http://localhost:3000 for now (or your deployed frontend URL)

---

### Step 4: Get Your Backend URL

After deployment:

1. **Railway:**
   - Go to your backend service
   - Click "Settings" → "Networking"
   - Click "Generate Domain" to get a free `.railway.app` domain
   - Copy the URL (e.g., https://price-radar-backend-production.up.railway.app)

2. **Render:**
   - Your service URL is shown in the service dashboard
   - Copy the URL (e.g., https://price-radar-api.onrender.com)

**Important:** Update your environment variables with this URL:
- `SHOPIFY_APP_URL` should be your backend URL

---

### Step 5: Configure Shopify App

1. **Go to Shopify Partner Dashboard**
   - Navigate to Apps → Your App → App setup

2. **Update URLs:**
   - **App URL**: `https://your-backend-url.com/api/shopify/install`
   - **Allowed redirection URL(s)**: `https://your-backend-url.com/api/shopify/callback`

   Replace `your-backend-url.com` with your actual Railway/Render URL.

3. **Verify Scopes:**
   - Ensure these scopes are selected:
     - read_products
     - write_products
     - read_orders

4. **Save Changes**

---

### Step 6: Verify Deployment

#### 1. Check Health Endpoint

```bash
curl https://your-backend-url.com/health
```

**Expected response:**
```json
{"status":"healthy"}
```

#### 2. Check Root Endpoint

```bash
curl https://your-backend-url.com/
```

**Expected response:**
```json
{"message":"Price Radar API","status":"running"}
```

#### 3. Check Database Migration

**Railway:**
```bash
railway run --service=backend alembic current
```

**Render:**
- Go to your backend service → Shell tab
- Run: `alembic current`

Should show the latest migration.

#### 4. Test OAuth Flow

1. Visit in your browser:
   ```
   https://your-backend-url.com/api/shopify/install?shop=your-dev-store
   ```
   Replace `your-dev-store` with your Shopify development store name.

2. You should be redirected to Shopify to authorize the app

3. After authorization, you should be redirected back with a JWT token

4. Check the logs to ensure no errors occurred

---

### Step 7: Verify Services

#### Check Logs

**Railway:**
- Click on each service (Backend, Worker, Beat)
- View live logs
- Look for:
  - ✅ "Application startup complete"
  - ✅ "Uvicorn running on..."
  - ✅ "celery@..." (for worker)
  - ✅ "beat: Starting..." (for beat)

**Render:**
- Go to each service → Logs tab
- Check for startup messages and no errors

#### Check Database

**Railway:**
```bash
railway run --service=backend psql $DATABASE_URL -c "\dt"
```

Should list all tables: shops, products, competitors, etc.

---

### Step 8: Test Complete OAuth Flow

1. **Install App on Dev Store**
   ```
   https://your-backend-url.com/api/shopify/install?shop=your-dev-store.myshopify.com
   ```

2. **Authorize on Shopify**
   - Click "Install" on the OAuth screen

3. **Verify Redirect**
   - Should redirect to your frontend (or localhost if FRONTEND_URL=http://localhost:3000)
   - URL should contain `?token=...`

4. **Test Authenticated Endpoint**
   ```bash
   # Extract the token from the URL, then:
   curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     https://your-backend-url.com/api/auth/me
   ```

   Should return your shop information.

---

### Step 9: Monitor and Troubleshoot

#### If Backend Won't Start:
1. Check logs for errors
2. Verify all environment variables are set
3. Ensure DATABASE_URL is correct
4. Check that migrations ran successfully

#### If Celery Worker Won't Start:
1. Check logs for connection errors
2. Verify REDIS_URL is correct
3. Ensure worker can connect to database

#### If OAuth Fails:
1. Verify Shopify App URLs match your deployment URLs exactly
2. Check SHOPIFY_API_SECRET is correct
3. Look for HMAC verification errors in logs

#### If You Get CORS Errors:
1. Verify FRONTEND_URL is set correctly in backend environment
2. Check that frontend URL is in the allowed_origins list
3. Restart backend service after changing CORS settings

---

## What's Been Prepared for You

I've created these files to help with deployment:

1. **Dockerfiles:**
   - `backend/Dockerfile` - Multi-stage production-optimized backend image
   - `backend/Dockerfile.celery` - Celery worker/beat image

2. **Configuration:**
   - `railway.json` - Railway deployment configuration
   - `docker-compose.staging.yml` - Local staging environment for testing
   - `backend/.env.staging.example` - Environment variable template

3. **Documentation:**
   - `docs/DEPLOYMENT.md` - Complete deployment guide with both Railway and Render
   - `docs/DEPLOYMENT_CHECKLIST.md` - Step-by-step checklist
   - This file - Manual steps you need to complete

4. **Scripts:**
   - `scripts/generate_secrets.py` - Generate secure JWT secret

5. **Code Updates:**
   - CORS configuration now supports staging/production URLs
   - Health check endpoint ready
   - Docker images optimized for production

---

## Next Steps After Deployment

1. **Test the Application**
   - Install on your dev store
   - Complete full OAuth flow
   - Make authenticated API requests
   - Verify data is being saved

2. **Set Up Monitoring (Optional but Recommended)**
   - Set up uptime monitoring (UptimeRobot, Pingdom)
   - Configure error tracking (Sentry)
   - Set up log aggregation

3. **Deploy Frontend (If Not Already Done)**
   - Deploy Next.js frontend to Railway/Render/Vercel
   - Update FRONTEND_URL environment variable
   - Test complete user flow

4. **Security Audit**
   - Verify all secrets are in environment variables
   - Ensure HTTPS is being used everywhere
   - Check database access is restricted

5. **Document Your Deployment**
   - Note all URLs (backend, frontend, databases)
   - Save configuration in secure location
   - Update team documentation

---

## Getting Help

If you run into issues:

1. **Check the logs** - Most issues are visible in service logs
2. **Review `docs/DEPLOYMENT.md`** - Detailed troubleshooting section
3. **Railway/Render Docs:**
   - Railway: https://docs.railway.app
   - Render: https://render.com/docs

4. **Create an issue** on GitHub with:
   - What you were trying to do
   - Error messages from logs
   - Environment (Railway/Render)
   - Steps you've already tried

---

## Summary Checklist

Use this quick checklist to track your progress:

- [ ] Generated JWT secret
- [ ] Created Railway/Render account
- [ ] Created new project
- [ ] Provisioned PostgreSQL database
- [ ] Provisioned Redis database
- [ ] Deployed backend service
- [ ] Deployed Celery worker
- [ ] Deployed Celery beat
- [ ] Added all environment variables
- [ ] Got backend URL from hosting provider
- [ ] Updated Shopify App URLs in Partner Dashboard
- [ ] Tested health endpoint
- [ ] Tested OAuth install flow
- [ ] Verified OAuth callback works
- [ ] Tested authenticated endpoints
- [ ] Checked all service logs for errors
- [ ] Verified database tables exist
- [ ] Tested complete end-to-end flow

**Once all items are checked, your staging environment is ready! 🎉**

---

## Important URLs to Save

After deployment, save these URLs:

- **Backend API**: https://__________.railway.app
- **PostgreSQL**: (internal only)
- **Redis**: (internal only)
- **Railway Dashboard**: https://railway.app/project/__________
- **Shopify Partner Dashboard**: https://partners.shopify.com/________/apps/__________

Good luck with your deployment! 🚀
