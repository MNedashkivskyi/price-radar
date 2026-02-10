# Price Radar

Monorepo for Price Radar application - Track prices across the web.

## Project Structure

```
.
├── backend/          # FastAPI backend with hexagonal architecture
├── frontend/         # Next.js React frontend
├── infra/           # Infrastructure configurations
└── docker-compose.yml
```

## Quick Start

### Using Docker Compose (Recommended)

```bash
docker-compose up -d
```

This will start:
- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`
- Backend API on `localhost:8000`
- Celery Worker
- Celery Beat
- Frontend on `localhost:3000`

### Local Development

#### Backend

```bash
cd backend
poetry install
cp .env.example .env
poetry run uvicorn price_radar.api.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Architecture

### Backend

FastAPI application with hexagonal architecture:
- `/domain` - Business entities and logic
- `/application` - Use cases and services
- `/infrastructure` - External integrations (DB, Redis, Celery)
- `/api` - FastAPI routes and controllers

### Database Migrations

```bash
cd backend
poetry run alembic upgrade head
poetry run alembic revision --autogenerate -m "description"
```

## Pre-commit Hooks

Install pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

Run manually:

```bash
pre-commit run --all-files
```

## Testing

```bash
cd backend
poetry run pytest
```

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js, React, TypeScript
- **Database**: PostgreSQL 16
- **Cache/Queue**: Redis 7
- **Code Quality**: Ruff, Black, Mypy, ESLint
- **CI/CD**: GitHub Actions

## CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment:

- **CI**: Runs tests, linting, and type checking on every push/PR
- **Docker Build**: Builds and pushes images to GHCR on master pushes and tags
- **Staging**: Auto-deploys on version tags (v*.*.*)
- **Production**: Manual deployment with approval workflow

See [.github/CICD.md](.github/CICD.md) for detailed documentation.

### Quick Release Process

```bash
# Create and push a version tag
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# Staging deploys automatically
# For production, use GitHub Actions UI to manually trigger deployment
```
