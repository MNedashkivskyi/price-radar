"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from price_radar.api import auth, competitors, onboarding, products, shopify
from price_radar.infrastructure.config import settings

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="0.1.0",
)

# Include routers
app.include_router(shopify.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(competitors.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")

# CORS middleware - Allow frontend origins
# In production, restrict this to specific domains
allowed_origins = [
    "http://localhost:3000",  # Local development
    "http://localhost:3001",  # Alternative local port
]

# Add staging/production frontend URL if configured
if settings.frontend_url and settings.frontend_url not in allowed_origins:
    allowed_origins.append(settings.frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Price Radar API", "status": "running"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
