# Shopify App Setup Guide

This guide walks you through the manual steps required to set up your Shopify App integration.

## Prerequisites

- Active email address
- Phone number for 2FA
- This Price Radar application running locally or deployed

---

## Step 1: Create Shopify Partner Account

### 1.1 Sign Up
1. Go to https://partners.shopify.com/signup
2. Fill in the registration form:
   - Email address
   - Password (strong password recommended)
   - Check "I agree to the Terms and Conditions"
3. Click **Create Account**

### 1.2 Verify Email
1. Check your email inbox
2. Click the verification link sent by Shopify
3. Complete any additional verification steps

### 1.3 Set Up 2FA (Two-Factor Authentication)
1. After email verification, you'll be prompted to set up 2FA
2. Choose your method:
   - **SMS** - Enter your phone number
   - **Authenticator App** - Use Google Authenticator or similar
3. Follow the prompts to complete 2FA setup

### 1.4 Complete Profile
1. Enter your business information:
   - Business name (can use "Price Radar" or your company name)
   - Business type (select appropriate option)
   - Country/region
2. Click **Save**

---

## Step 2: Create Development Store

### 2.1 Navigate to Stores
1. From the Partner Dashboard, click **Stores** in the left sidebar
2. Click **Add store** button

### 2.2 Create Development Store
1. Select **Development store**
2. Fill in store details:
   - **Store name**: `price-radar-dev` (or your preferred name)
   - **Store URL**: Will auto-populate (e.g., `price-radar-dev.myshopify.com`)
   - **Password**: Create a password for store login
   - **Store purpose**: Select "Test an app or theme"
3. Click **Save**

### 2.3 Access Your Dev Store
1. Wait for store creation (takes a few seconds)
2. Note your store URL: `https://price-radar-dev.myshopify.com`
3. You can click **Log in** to access the store admin

---

## Step 3: Register Your App

### 3.1 Create App
1. From Partner Dashboard, click **Apps** in the left sidebar
2. Click **Create app** button
3. Choose **Public app** (for distribution) or **Custom app** (for specific stores)
   - For testing: Choose **Public app**
4. Fill in app details:
   - **App name**: `Price Radar`
   - **App URL**: `https://your-domain.com` (or `http://localhost:8000` for local testing)
   - **Allowed redirection URL(s)**:
     ```
     http://localhost:8000/api/shopify/callback
     ```
     (Add more URLs for staging/production later)
5. Click **Create app**

### 3.2 Configure App Scopes

1. After creating the app, go to **Configuration** tab
2. Scroll to **API access** section
3. Click **Configure** under "Admin API access scopes"
4. Select the following scopes:

   **Required Scopes:**
   - ✅ `read_products` - Read products
   - ✅ `write_products` - Write products
   - ✅ `read_orders` - Read orders

5. Click **Save** at the bottom

### 3.3 Get API Credentials

1. In the **Configuration** tab, find the **Client credentials** section
2. Copy and save these values (you'll need them later):
   - **API key** (also called Client ID)
   - **API secret key** (also called Client Secret)

⚠️ **IMPORTANT**: Keep these credentials secure! Never commit them to version control.

---

## Step 4: Configure OAuth Redirect URLs

### 4.1 Add Redirect URLs
1. In app configuration, scroll to **App URL** section
2. Under **Allowed redirection URL(s)**, ensure you have:

   **For Local Development:**
   ```
   http://localhost:8000/api/shopify/callback
   ```

   **For Production** (add these when you deploy):
   ```
   https://api.price-radar.com/api/shopify/callback
   https://staging-api.price-radar.com/api/shopify/callback
   ```

3. Click **Save**

### 4.2 Configure App Proxy (Optional, for embedded apps)
1. Scroll to **App proxy** section
2. Configure if you want to serve content on the store:
   - **Subpath prefix**: `apps`
   - **Subpath**: `price-radar`
   - **Proxy URL**: `https://your-domain.com/api/shopify/proxy`
3. Click **Save**

---

## Step 5: Set Up Environment Variables

After completing the above steps, update your backend `.env` file:

```bash
# Shopify App Credentials
SHOPIFY_API_KEY=your_api_key_here
SHOPIFY_API_SECRET=your_api_secret_here
SHOPIFY_APP_URL=http://localhost:8000
SHOPIFY_SCOPES=read_products,write_products,read_orders

# For production, also set:
# SHOPIFY_APP_URL=https://api.price-radar.com
```

### 5.1 How to Add Environment Variables

**For Local Development:**
```bash
cd backend
echo "SHOPIFY_API_KEY=your_api_key_here" >> .env
echo "SHOPIFY_API_SECRET=your_api_secret_here" >> .env
echo "SHOPIFY_APP_URL=http://localhost:8000" >> .env
echo "SHOPIFY_SCOPES=read_products,write_products,read_orders" >> .env
```

**For GitHub Actions (Production):**
1. Go to GitHub repository → Settings → Secrets and variables → Actions
2. Add new repository secrets:
   - `SHOPIFY_API_KEY`
   - `SHOPIFY_API_SECRET`
   - `SHOPIFY_APP_URL`
   - `SHOPIFY_SCOPES`

---

## Step 6: Install App on Development Store

### 6.1 Generate Installation URL
After the backend code is deployed, generate an installation URL:

```
https://{shop}.myshopify.com/admin/oauth/authorize?client_id={api_key}&scope={scopes}&redirect_uri={redirect_uri}
```

**Example:**
```
https://price-radar-dev.myshopify.com/admin/oauth/authorize?client_id=YOUR_API_KEY&scope=read_products,write_products,read_orders&redirect_uri=http://localhost:8000/api/shopify/callback
```

### 6.2 Install the App
1. Navigate to the installation URL in your browser
2. You'll be redirected to Shopify
3. Review the permissions requested
4. Click **Install app**
5. You'll be redirected to your callback URL
6. The app will receive an access token and store it in the database

### 6.3 Verify Installation
1. Go to your dev store admin: `https://price-radar-dev.myshopify.com/admin`
2. Click **Apps** in the left sidebar
3. You should see **Price Radar** listed
4. Click on it to verify it's working

---

## Step 7: Test the Integration

### 7.1 Check Database
Verify the shop data was stored:
```sql
SELECT * FROM shopify_stores;
```

You should see a record with:
- Shop domain (e.g., `price-radar-dev.myshopify.com`)
- Access token (encrypted)
- Scopes granted
- Installation timestamp

### 7.2 Test API Access
Use the stored access token to make a test API call:

```python
import requests

shop = "price-radar-dev.myshopify.com"
access_token = "your_access_token"

response = requests.get(
    f"https://{shop}/admin/api/2024-01/products.json",
    headers={"X-Shopify-Access-Token": access_token}
)

print(response.json())
```

---

## Troubleshooting

### Error: "Invalid redirect_uri"
- Ensure the redirect URI in your installation URL exactly matches what's configured in the Partner Dashboard
- Check for trailing slashes
- Verify the protocol (http vs https)

### Error: "Invalid API key or access token"
- Double-check your API credentials in `.env`
- Ensure you're using the correct API version
- Verify the access token hasn't been revoked

### Error: "Insufficient permissions"
- Check that all required scopes are configured in Partner Dashboard
- Reinstall the app to get updated scopes
- Verify scopes in the database match what you requested

### App Not Showing in Dev Store
- Check that the app installation completed successfully
- Look for errors in the callback endpoint logs
- Verify the access token was saved to the database

---

## Next Steps

After completing the setup:

1. ✅ Run database migrations: `poetry run alembic upgrade head`
2. ✅ Start the backend server: `poetry run uvicorn price_radar.api.main:app --reload`
3. ✅ Generate and visit the installation URL
4. ✅ Complete the OAuth flow
5. ✅ Verify the shop data in the database
6. ✅ Test API calls using the stored access token

---

## Security Best Practices

1. **Never expose API credentials**
   - Keep `.env` file out of version control
   - Use environment variables in production
   - Rotate secrets regularly

2. **Validate all requests**
   - Verify HMAC signatures on webhooks
   - Check nonce values during OAuth
   - Validate shop domains

3. **Store tokens securely**
   - Encrypt access tokens in database
   - Use secure HTTPS connections
   - Implement token rotation if needed

4. **Limit scope access**
   - Only request scopes you actually need
   - Review scopes regularly
   - Document why each scope is required

---

## Useful Links

- [Shopify Partner Dashboard](https://partners.shopify.com)
- [Shopify API Documentation](https://shopify.dev/docs/api)
- [OAuth Documentation](https://shopify.dev/docs/apps/auth/oauth)
- [API Rate Limits](https://shopify.dev/docs/api/usage/rate-limits)
- [Webhooks Guide](https://shopify.dev/docs/apps/webhooks)

---

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review Shopify API logs in Partner Dashboard
3. Check backend application logs
4. Consult Shopify documentation
5. Contact Shopify Partner Support
