# Staging Deployment Checklist

Use this checklist to ensure all steps are completed for a successful staging deployment.

## Pre-Deployment

### 1. Code Preparation
- [ ] All tests passing locally (`pytest`)
- [ ] Linting passes (`ruff check .`)
- [ ] Code formatted (`black .`)
- [ ] Latest code pushed to `master` branch
- [ ] Dockerfiles build successfully locally

### 2. Shopify App Setup
- [ ] Shopify Partner account created
- [ ] App created in Partner Dashboard
- [ ] App name configured
- [ ] App scopes set: `read_products,write_products,read_orders`
- [ ] Development store created

### 3. Generate Secrets
```bash
# Generate JWT secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
- [ ] JWT secret key generated and saved securely

## Railway Deployment (Recommended)

### Step 1: Create Railway Project
- [ ] Railway account created at https://railway.app
- [ ] New project created: `price-radar-staging`
- [ ] Project region selected (closest to your location)

### Step 2: Provision Databases
- [ ] PostgreSQL database added to project
- [ ] Redis database added to project
- [ ] Database credentials noted (automatic in Railway)

### Step 3: Deploy Backend API
- [ ] GitHub repository connected
- [ ] Backend service created from repo
- [ ] Dockerfile detected: `backend/Dockerfile`
- [ ] Environment variables configured (see list below)
- [ ] Service deployed successfully
- [ ] Public domain generated or custom domain added
- [ ] Health check passing: `https://your-backend.railway.app/health`

#### Backend Environment Variables
- [ ] `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
- [ ] `REDIS_URL` = `${{Redis.REDIS_URL}}`
- [ ] `CELERY_BROKER_URL` = `${{Redis.REDIS_URL}}/1`
- [ ] `CELERY_RESULT_BACKEND` = `${{Redis.REDIS_URL}}/2`
- [ ] `APP_NAME` = `Price Radar API`
- [ ] `DEBUG` = `false`
- [ ] `SHOPIFY_API_KEY` = `<from Partner Dashboard>`
- [ ] `SHOPIFY_API_SECRET` = `<from Partner Dashboard>`
- [ ] `SHOPIFY_APP_URL` = `https://your-backend.railway.app`
- [ ] `SHOPIFY_SCOPES` = `read_products,write_products,read_orders`
- [ ] `SHOPIFY_API_VERSION` = `2024-01`
- [ ] `JWT_SECRET_KEY` = `<generated 32-byte key>`
- [ ] `JWT_ALGORITHM` = `HS256`
- [ ] `JWT_EXPIRATION_HOURS` = `24`
- [ ] `FRONTEND_URL` = `https://your-frontend.railway.app`

### Step 4: Deploy Celery Worker
- [ ] New service created from same repo
- [ ] Dockerfile path set: `backend/Dockerfile.celery`
- [ ] Start command set: `celery -A price_radar.infrastructure.celery_app worker --loglevel=info`
- [ ] Same environment variables as backend configured
- [ ] Service deployed and running
- [ ] Worker logs show "ready" status

### Step 5: Deploy Celery Beat
- [ ] New service created from same repo
- [ ] Dockerfile path set: `backend/Dockerfile.celery`
- [ ] Start command set: `celery -A price_radar.infrastructure.celery_app beat --loglevel=info`
- [ ] Same environment variables configured
- [ ] Service deployed and running
- [ ] Beat logs show scheduler started

### Step 6: Deploy Frontend (Optional for MVP)
- [ ] New service created from repo
- [ ] Root directory set: `frontend`
- [ ] Build command: `npm install && npm run build`
- [ ] Start command: `npm start`
- [ ] Environment variable `NEXT_PUBLIC_API_URL` set
- [ ] Service deployed successfully
- [ ] Frontend accessible via HTTPS

## Shopify App Configuration

### Update App URLs
- [ ] Login to Shopify Partner Dashboard
- [ ] Navigate to your app settings
- [ ] Update **App URL**: `https://your-backend.railway.app/api/shopify/install`
- [ ] Update **Allowed redirection URLs**: `https://your-backend.railway.app/api/shopify/callback`
- [ ] Save changes

### OAuth Scopes
- [ ] Verify scopes match what's configured in code
- [ ] Request any additional permissions needed
- [ ] Save configuration

## Post-Deployment Verification

### 1. Backend Health Checks
```bash
# Test health endpoint
curl https://your-backend.railway.app/health
# Expected: {"status":"healthy"}

# Test root endpoint
curl https://your-backend.railway.app/
# Expected: {"message":"Price Radar API","status":"running"}
```
- [ ] Health endpoint returns healthy status
- [ ] Root endpoint accessible

### 2. Database Connectivity
- [ ] Check backend logs for successful database connection
- [ ] Verify migrations ran successfully
- [ ] Query database to confirm tables exist

**Railway Shell:**
```bash
railway run psql $DATABASE_URL -c "\dt"
```

- [ ] Tables created: `shops`, `products`, `competitors`, etc.

### 3. Redis Connectivity
```bash
# Test Redis connection
railway run python -c "import redis; r = redis.from_url('$REDIS_URL'); print(r.ping())"
```
- [ ] Redis ping returns True

### 4. Celery Worker Status
- [ ] Check worker logs in Railway dashboard
- [ ] Verify worker is connected to broker
- [ ] Confirm worker is ready to process tasks

### 5. Celery Beat Status
- [ ] Check beat logs in Railway dashboard
- [ ] Verify beat scheduler started
- [ ] Confirm periodic tasks are being scheduled

### 6. OAuth Flow Test
```bash
# Visit install URL in browser
https://your-backend.railway.app/api/shopify/install?shop=your-dev-store
```
- [ ] Redirects to Shopify authorization page
- [ ] Can authorize the app
- [ ] Redirects back to callback endpoint
- [ ] HMAC signature verified successfully
- [ ] Shop record created in database
- [ ] JWT token generated
- [ ] Redirects to frontend dashboard with token

### 7. Authentication Test
```bash
# Extract JWT from OAuth flow, then test:
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  https://your-backend.railway.app/api/auth/me

# Expected: Shop information
```
- [ ] JWT authentication working
- [ ] Protected endpoints accessible with valid token
- [ ] 401 error returned for invalid/missing tokens

### 8. HTTPS & SSL
- [ ] All URLs use HTTPS
- [ ] SSL certificate valid
- [ ] No mixed content warnings
- [ ] Railway/Render provides automatic HTTPS

### 9. CORS Configuration
- [ ] Frontend can make API requests
- [ ] No CORS errors in browser console
- [ ] Credentials being sent correctly

### 10. Error Monitoring
- [ ] Review Railway/Render logs for errors
- [ ] No critical errors in backend logs
- [ ] No errors in worker logs
- [ ] No errors in beat logs

## Performance Checks

### Response Times
```bash
# Measure API response time
curl -w "@-" -o /dev/null -s https://your-backend.railway.app/health << 'EOF'
    time_namelookup:  %{time_namelookup}s\n
       time_connect:  %{time_connect}s\n
    time_appconnect:  %{time_appconnect}s\n
   time_pretransfer:  %{time_pretransfer}s\n
      time_redirect:  %{time_redirect}s\n
 time_starttransfer:  %{time_starttransfer}s\n
                    ----------\n
         time_total:  %{time_total}s\n
EOF
```
- [ ] Response times under 500ms
- [ ] No significant latency

### Resource Usage
- [ ] Backend memory usage normal (<512MB for hobby)
- [ ] CPU usage reasonable
- [ ] Database connections within limits

## Security Audit

### Secrets Management
- [ ] No secrets in code or committed to git
- [ ] All secrets in environment variables
- [ ] JWT secret is strong (32+ bytes)
- [ ] Database password is strong

### HTTPS & Encryption
- [ ] All traffic over HTTPS
- [ ] TLS 1.2 or higher
- [ ] Shopify access tokens encrypted at rest

### Access Control
- [ ] Database not publicly accessible (internal only)
- [ ] Redis not publicly accessible
- [ ] Only backend service exposed publicly

## Documentation

- [ ] Deployment guide updated: `docs/DEPLOYMENT.md`
- [ ] Environment variables documented
- [ ] Architecture diagram created (optional)
- [ ] Runbook created for common operations

## Monitoring & Alerts

- [ ] Set up uptime monitoring (optional: UptimeRobot, Pingdom)
- [ ] Configure error alerts (optional: Sentry, Railway notifications)
- [ ] Set up log aggregation (built-in with Railway/Render)
- [ ] Document incident response procedures

## Backup & Recovery

- [ ] Database backup strategy in place
- [ ] Backup restoration tested (optional for staging)
- [ ] Critical data identified
- [ ] Recovery time objectives (RTO) defined

## Cost Optimization

- [ ] Review Railway/Render usage
- [ ] Confirm within budget ($5-10/month expected)
- [ ] No unnecessary services running
- [ ] Resource limits configured appropriately

## Team Access

- [ ] Team members invited to Railway/Render project
- [ ] Access permissions configured
- [ ] Environment variable access controlled
- [ ] Deployment permissions set

## Final Verification

### End-to-End Test
1. - [ ] Install app on Shopify dev store
2. - [ ] Complete OAuth flow
3. - [ ] Receive JWT token
4. - [ ] Make authenticated API call
5. - [ ] Verify data in database
6. - [ ] Check Celery task processing (if applicable)

### Load Test (Optional)
- [ ] Basic load test with 10-100 concurrent users
- [ ] Response times acceptable under load
- [ ] No errors during load test
- [ ] Resources scale appropriately

## Go-Live Approval

- [ ] All checklist items completed
- [ ] No critical issues outstanding
- [ ] Team reviewed and approved
- [ ] Stakeholders notified of staging URL
- [ ] Ready for testing by QA/Product team

## Post-Deployment Tasks

- [ ] Share staging URL with team
- [ ] Add to project documentation
- [ ] Schedule review meeting
- [ ] Plan production deployment
- [ ] Document lessons learned

---

## Quick Reference

### Important URLs
- **Backend API**: https://your-backend.railway.app
- **Frontend**: https://your-frontend.railway.app
- **Health Check**: https://your-backend.railway.app/health
- **OAuth Install**: https://your-backend.railway.app/api/shopify/install?shop=store-name

### Common Commands

**Generate JWT Secret:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Test Health:**
```bash
curl https://your-backend.railway.app/health
```

**View Logs (Railway):**
```bash
railway logs
```

**Run Database Migrations:**
```bash
railway run alembic upgrade head
```

**Access Database:**
```bash
railway run psql
```

### Support Contacts
- **Railway Support**: https://railway.app/help
- **Shopify Partner Support**: https://partners.shopify.com/support
- **Team Lead**: [Contact Info]
- **DevOps**: [Contact Info]

---

## Troubleshooting

If any check fails, refer to `docs/DEPLOYMENT.md` troubleshooting section for solutions.

Common issues:
- Database connection failures → Check DATABASE_URL
- OAuth fails → Verify Shopify App URLs match deployment
- CORS errors → Update allowed origins in backend
- Celery won't start → Check Redis connection
- Migrations fail → Run manually via Railway shell
