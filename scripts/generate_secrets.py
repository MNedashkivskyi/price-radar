#!/usr/bin/env python3
"""Generate secure secrets for production deployment."""

import secrets

if __name__ == "__main__":
    print("=" * 60)
    print("Price Radar - Secret Key Generator")
    print("=" * 60)
    print()
    print("Copy these values to your .env or hosting provider:")
    print()
    print("-" * 60)
    print("JWT_SECRET_KEY:")
    print(secrets.token_urlsafe(32))
    print("-" * 60)
    print()
    print("Store these securely and never commit to version control!")
    print()
