"""API middleware for authentication and request processing."""

import jwt
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.src.price_radar.application.jwt_service import JWTService

# Security scheme for JWT bearer tokens
security = HTTPBearer(auto_error=False)


async def get_current_shop_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> int:
    """Extract and validate shop_id from JWT token.

    This dependency can be used in protected endpoints to get the authenticated shop ID.

    Args:
        request: FastAPI request object
        credentials: Optional HTTP bearer credentials

    Returns:
        Shop ID from JWT token

    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    # Try to get token from Authorization header
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # Try to get from Authorization header manually
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        jwt_service = JWTService()
        shop_id = jwt_service.get_shop_id_from_token(token)
        return shop_id
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_optional_shop_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> int | None:
    """Optionally extract shop_id from JWT token without raising errors.

    Useful for endpoints that support both authenticated and unauthenticated access.

    Args:
        request: FastAPI request object
        credentials: Optional HTTP bearer credentials

    Returns:
        Shop ID if token is valid, None otherwise
    """
    try:
        return await get_current_shop_id(request, credentials)
    except HTTPException:
        return None


def get_token_from_request(request: Request) -> str | None:
    """Extract JWT token from request headers.

    Args:
        request: FastAPI request object

    Returns:
        JWT token if present, None otherwise
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "")
    return None
