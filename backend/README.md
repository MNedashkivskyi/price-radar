# Price Radar Backend

FastAPI backend with hexagonal architecture.

## Setup

```bash
cd backend
poetry install
poetry run uvicorn price_radar.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Architecture

- `/domain` - Business logic and entities
- `/application` - Use cases and application services
- `/infrastructure` - External integrations (DB, Redis, etc.)
- `/api` - FastAPI routes and controllers
