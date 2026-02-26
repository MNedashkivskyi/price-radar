"""JWT authentication service."""

from datetime import datetime, timedelta
from typing import Any

import jwt

from price_radar.infrastructure.config import settings


class JWTService:
    """Service for JWT token generation and validation."""

    def __init__(self) -> None:
        """Initialize JWT service."""
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.expiration_hours = settings.jwt_expiration_hours

    def create_session_token(self, shop_id: int, shop_domain: str) -> str:
        """Create a JWT session token for a shop.

        Args:
            shop_id: Shop database ID
            shop_domain: Shop's Shopify domain

        Returns:
            JWT token string
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=self.expiration_hours)

        payload: dict[str, Any] = {
            "shop_id": shop_id,
            "shop_domain": shop_domain,
            "iat": now,
            "exp": expires_at,
            "type": "session",
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return str(token)

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify and decode a JWT token.

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            jwt.InvalidTokenError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return dict(payload)
        except jwt.ExpiredSignatureError as e:
            raise jwt.InvalidTokenError("Token has expired") from e
        except jwt.InvalidTokenError as e:
            raise jwt.InvalidTokenError("Invalid token") from e

    def verify_token_allow_expired(self, token: str) -> dict[str, Any]:
        """Verify a JWT token's signature but allow expired tokens.

        Used by the refresh endpoint so users can exchange an expired token
        for a new one without hitting a 401 loop.

        Args:
            token: JWT token string

        Returns:
            Decoded token payload (even if expired)

        Raises:
            jwt.InvalidTokenError: If token signature is invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_exp": False},
            )
            return dict(payload)
        except jwt.InvalidTokenError as e:
            raise jwt.InvalidTokenError("Invalid token") from e

    def get_shop_id_from_token(self, token: str) -> int:
        """Extract shop_id from a JWT token.

        Args:
            token: JWT token string

        Returns:
            Shop ID

        Raises:
            jwt.InvalidTokenError: If token is invalid or expired
        """
        payload = self.verify_token(token)
        shop_id = payload.get("shop_id")

        if not shop_id:
            raise jwt.InvalidTokenError("Token does not contain shop_id")

        return int(shop_id)

    def get_shop_id_from_token_allow_expired(self, token: str) -> int:
        """Extract shop_id from a JWT token, allowing expired tokens.

        Used by the refresh endpoint so expired tokens can still be exchanged.

        Args:
            token: JWT token string

        Returns:
            Shop ID

        Raises:
            jwt.InvalidTokenError: If token signature is invalid
        """
        payload = self.verify_token_allow_expired(token)
        shop_id = payload.get("shop_id")

        if not shop_id:
            raise jwt.InvalidTokenError("Token does not contain shop_id")

        return int(shop_id)
