"""Tests for JWT authentication."""

from datetime import datetime, timedelta

import jwt
import pytest
from backend.src.price_radar.application.jwt_service import JWTService


def test_create_session_token() -> None:
    """Test JWT session token creation."""
    jwt_service = JWTService()
    jwt_service.secret_key = "test-secret-key"  # Override for testing

    shop_id = 123
    shop_domain = "test-shop.myshopify.com"

    token = jwt_service.create_session_token(shop_id, shop_domain)

    assert isinstance(token, str)
    assert len(token) > 0


def test_verify_valid_token() -> None:
    """Test verifying a valid JWT token."""
    jwt_service = JWTService()
    jwt_service.secret_key = "test-secret-key"

    shop_id = 123
    shop_domain = "test-shop.myshopify.com"

    token = jwt_service.create_session_token(shop_id, shop_domain)
    payload = jwt_service.verify_token(token)

    assert payload["shop_id"] == shop_id
    assert payload["shop_domain"] == shop_domain
    assert payload["type"] == "session"
    assert "iat" in payload
    assert "exp" in payload


def test_verify_invalid_token() -> None:
    """Test verifying an invalid JWT token."""
    jwt_service = JWTService()
    jwt_service.secret_key = "test-secret-key"

    invalid_token = "invalid.token.here"

    with pytest.raises(jwt.InvalidTokenError):
        jwt_service.verify_token(invalid_token)


def test_verify_expired_token() -> None:
    """Test verifying an expired JWT token."""
    from datetime import datetime, timedelta

    jwt_service = JWTService()
    jwt_service.secret_key = "test-secret-key"

    # Create a token that expired 1 hour ago
    payload = {
        "shop_id": 123,
        "shop_domain": "test-shop.myshopify.com",
        "iat": datetime.utcnow() - timedelta(hours=2),
        "exp": datetime.utcnow() - timedelta(hours=1),
        "type": "session",
    }

    expired_token = jwt.encode(payload, jwt_service.secret_key, algorithm=jwt_service.algorithm)

    with pytest.raises(jwt.InvalidTokenError):
        jwt_service.verify_token(expired_token)


def test_get_shop_id_from_token() -> None:
    """Test extracting shop_id from JWT token."""
    jwt_service = JWTService()
    jwt_service.secret_key = "test-secret-key"

    shop_id = 456
    shop_domain = "another-shop.myshopify.com"

    token = jwt_service.create_session_token(shop_id, shop_domain)
    extracted_shop_id = jwt_service.get_shop_id_from_token(token)

    assert extracted_shop_id == shop_id


def test_get_shop_id_from_token_without_shop_id() -> None:
    """Test extracting shop_id from token that doesn't have shop_id."""
    jwt_service = JWTService()
    jwt_service.secret_key = "test-secret-key"

    # Create token without shop_id
    payload = {
        "some_other_field": "value",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=1),
    }

    token = jwt.encode(payload, jwt_service.secret_key, algorithm=jwt_service.algorithm)

    with pytest.raises(jwt.InvalidTokenError, match="does not contain shop_id"):
        jwt_service.get_shop_id_from_token(token)


def test_token_with_wrong_secret() -> None:
    """Test that token created with one secret can't be verified with another."""
    jwt_service1 = JWTService()
    jwt_service1.secret_key = "secret-key-1"

    jwt_service2 = JWTService()
    jwt_service2.secret_key = "secret-key-2"

    token = jwt_service1.create_session_token(123, "test-shop.myshopify.com")

    with pytest.raises(jwt.InvalidTokenError):
        jwt_service2.verify_token(token)
