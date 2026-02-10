# CI/CD Pipeline Documentation

This document describes the CI/CD pipeline setup for Price Radar.

## Overview

The CI/CD pipeline consists of three main workflows:

1. **CI (Continuous Integration)** - Runs on every push and PR
2. **Docker Build** - Builds and pushes Docker images on master pushes and tags
3. **Deployments** - Deploys to staging (automatic on tags) and production (manual)

## Workflows

### 1. CI Workflow (`ci.yml`)

**Triggers:**
- Push to `master` or `develop` branches
- Pull requests to `master` or `develop`

**Jobs:**

#### Backend Lint & Type Check
- Runs Ruff (linting)
- Runs Black (code formatting check)
- Runs Mypy (type checking)

#### Backend Tests
- Sets up PostgreSQL 16 and Redis 7 services
- Runs pytest with coverage
- Uploads coverage to Codecov

#### Frontend Lint & Type Check
- Runs ESLint
- Runs TypeScript type checking

#### Frontend Tests
- Runs tests (currently placeholder)
- Builds the application

### 2. Docker Build Workflow (`docker-build.yml`)

**Triggers:**
- Push to `master` branch
- New version tags (v*.*.*)
- Manual workflow dispatch

**Jobs:**
- Builds backend Docker image
- Builds frontend Docker image
- Pushes images to GitHub Container Registry (GHCR)
- Tags images with:
  - Branch name
  - Semantic version (from git tags)
  - Git SHA

**Image Locations:**
- Backend: `ghcr.io/<owner>/price-radar/backend`
- Frontend: `ghcr.io/<owner>/price-radar/frontend`

### 3. Staging Deployment (`deploy-staging.yml`)

**Triggers:**
- New version tags (v*.*.*)
- Manual workflow dispatch

**Process:**
1. Validates the tag
2. Deploys to staging environment
3. Runs database migrations
4. Runs smoke tests
5. Notifies on success/failure

**Deployment Options:**
- Railway (cloud platform)
- SSH to custom server

### 4. Production Deployment (`deploy-production.yml`)

**Triggers:**
- Manual workflow dispatch only

**Safety Features:**
- Requires manual confirmation ("DEPLOY" keyword)
- Validates tag exists
- Creates database backup before deployment
- Runs smoke tests
- Rollback on failure

**Process:**
1. Validates deployment request
2. Creates database backup
3. Deploys to production
4. Runs migrations
5. Runs smoke tests
6. Rolls back on failure

## Required Secrets

### GitHub Secrets

Configure these in your repository settings: `Settings → Secrets and variables → Actions`

#### For Docker Image Push
- `GITHUB_TOKEN` (automatically provided by GitHub)

#### For Railway Deployment
- `RAILWAY_TOKEN_STAGING` - Railway API token for staging
- `RAILWAY_TOKEN_PRODUCTION` - Railway API token for production

#### For SSH Deployment (Staging)
- `STAGING_HOST` - SSH host for staging server
- `STAGING_USERNAME` - SSH username
- `STAGING_SSH_KEY` - Private SSH key
- `STAGING_PORT` - SSH port (optional, default 22)

#### For SSH Deployment (Production)
- `PRODUCTION_HOST` - SSH host for production server
- `PRODUCTION_USERNAME` - SSH username
- `PRODUCTION_SSH_KEY` - Private SSH key
- `PRODUCTION_PORT` - SSH port (optional, default 22)

### GitHub Variables

Configure these in `Settings → Secrets and variables → Actions → Variables`

#### Deployment Configuration
- `DEPLOY_PLATFORM` - Either "railway" or "ssh"
- `STAGING_BACKEND_URL` - Backend URL for staging smoke tests
- `STAGING_FRONTEND_URL` - Frontend URL for staging smoke tests
- `PRODUCTION_BACKEND_URL` - Backend URL for production smoke tests
- `PRODUCTION_FRONTEND_URL` - Frontend URL for production smoke tests

### Environment Setup

Create two environments in `Settings → Environments`:

1. **staging**
   - No protection rules (auto-deploy on tags)

2. **production**
   - Required reviewers (add team members)
   - Protection rules enabled

## Release Process

### 1. Development
```bash
# Work on feature branch
git checkout -b feature/my-feature
# Make changes, commit
git push origin feature/my-feature
# Create PR to master
```

### 2. Merge to Master
- CI runs automatically
- All checks must pass
- After merge, Docker images are built

### 3. Create Release Tag
```bash
git checkout master
git pull
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

### 4. Staging Deployment
- Automatically triggers on tag push
- Deploys to staging environment
- Runs smoke tests

### 5. Production Deployment
```bash
# Go to GitHub Actions
# Select "Deploy to Production" workflow
# Click "Run workflow"
# Enter tag: v1.0.0
# Enter confirmation: DEPLOY
# Click "Run workflow"
```

## Monitoring

### Check Workflow Status
- GitHub Actions tab in repository
- View logs for each job
- Check coverage reports

### Verify Deployments
- Staging: Check `STAGING_BACKEND_URL/health`
- Production: Check `PRODUCTION_BACKEND_URL/health`

## Rollback Procedure

### Automatic Rollback
- Production deployment has automatic rollback on failure
- Database backup is created before deployment

### Manual Rollback
```bash
# Re-deploy previous stable version
# Go to GitHub Actions → Deploy to Production
# Enter previous stable tag
# Confirm deployment
```

## Troubleshooting

### CI Failures
1. Check job logs in GitHub Actions
2. Run tests locally: `cd backend && poetry run pytest`
3. Run linting: `poetry run ruff check .`
4. Fix issues and push

### Docker Build Failures
1. Check Dockerfile syntax
2. Test build locally: `docker build -t test ./backend`
3. Check image size and dependencies

### Deployment Failures
1. Check deployment logs
2. Verify secrets are configured
3. Check server connectivity (SSH)
4. Verify database is accessible
5. Check disk space on server

### Database Migration Issues
```bash
# SSH to server
cd /opt/price-radar
docker-compose exec backend poetry run alembic current
docker-compose exec backend poetry run alembic history
# Rollback if needed
docker-compose exec backend poetry run alembic downgrade -1
```

## Best Practices

1. **Always test locally before pushing**
2. **Write meaningful commit messages**
3. **Tag releases with semantic versioning**
4. **Monitor staging before promoting to production**
5. **Keep secrets secure and rotate regularly**
6. **Review deployment logs after each release**
7. **Maintain database backups**

## Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [Railway Documentation](https://docs.railway.app/)
