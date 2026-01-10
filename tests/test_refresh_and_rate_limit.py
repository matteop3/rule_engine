#!/usr/bin/env python3
"""
Test script for Refresh Token and Rate Limiting features.

This script tests:
1. Login endpoint returns both access and refresh tokens
2. Refresh endpoint works correctly
3. Rate limiting is enforced on login endpoint
4. Rate limiting is enforced on refresh endpoint
"""

import requests
import time
from typing import Optional

BASE_URL = "http://localhost:8000"
AUTH_URL = f"{BASE_URL}/auth"

# Test credentials (make sure a user exists with these credentials)
TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "TestPassword123!"


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def test_login() -> tuple[Optional[str], Optional[str]]:
    """Test login endpoint and check for both tokens."""
    print_section("TEST 1: Login with Refresh Token")

    try:
        response = requests.post(
            f"{AUTH_URL}/token",
            data={
                "username": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"✓ Login successful!")
            print(f"  - Access Token: {data.get('access_token', 'N/A')[:50]}...")
            print(f"  - Refresh Token: {data.get('refresh_token', 'N/A')[:50]}...")
            print(f"  - Token Type: {data.get('token_type', 'N/A')}")

            return data.get('access_token'), data.get('refresh_token')
        else:
            print(f"✗ Login failed: {response.text}")
            return None, None

    except Exception as e:
        print(f"✗ Error: {e}")
        return None, None


def test_refresh(refresh_token: str) -> Optional[str]:
    """Test refresh endpoint."""
    print_section("TEST 2: Refresh Access Token")

    try:
        response = requests.post(
            f"{AUTH_URL}/refresh",
            headers={
                "Authorization": f"Bearer {refresh_token}"
            }
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"✓ Token refreshed successfully!")
            print(f"  - New Access Token: {data.get('access_token', 'N/A')[:50]}...")
            return data.get('access_token')
        else:
            print(f"✗ Refresh failed: {response.text}")
            return None

    except Exception as e:
        print(f"✗ Error: {e}")
        return None


def test_login_rate_limit():
    """Test login rate limiting."""
    print_section("TEST 3: Login Rate Limiting (5 attempts / 15 min)")

    print("Attempting 6 consecutive logins to trigger rate limit...")

    for i in range(6):
        try:
            response = requests.post(
                f"{AUTH_URL}/token",
                data={
                    "username": TEST_EMAIL,
                    "password": "wrong_password"  # Use wrong password to not lock account
                }
            )

            print(f"  Attempt {i+1}: Status {response.status_code}", end="")

            if response.status_code == 429:
                print(" - ✓ RATE LIMITED!")
                print(f"    Response: {response.json()}")
                return True
            elif response.status_code == 401:
                print(" - Failed (expected)")
            else:
                print(f" - {response.text}")

            time.sleep(0.5)  # Small delay between requests

        except Exception as e:
            print(f"  Attempt {i+1}: Error - {e}")

    print("✗ Rate limiting was NOT triggered after 6 attempts")
    return False


def test_refresh_rate_limit(refresh_token: str):
    """Test refresh rate limiting."""
    print_section("TEST 4: Refresh Rate Limiting (10 attempts / 5 min)")

    print("Attempting 12 consecutive refresh requests to trigger rate limit...")

    for i in range(12):
        try:
            response = requests.post(
                f"{AUTH_URL}/refresh",
                headers={
                    "Authorization": f"Bearer {refresh_token}"
                }
            )

            print(f"  Attempt {i+1}: Status {response.status_code}", end="")

            if response.status_code == 429:
                print(" - ✓ RATE LIMITED!")
                print(f"    Response: {response.json()}")
                return True
            elif response.status_code == 200:
                print(" - Success")
            else:
                print(f" - {response.text}")

            time.sleep(0.3)  # Small delay between requests

        except Exception as e:
            print(f"  Attempt {i+1}: Error - {e}")

    print("✗ Rate limiting was NOT triggered after 12 attempts")
    return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  REFRESH TOKEN & RATE LIMITING TEST SUITE")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"Test User: {TEST_EMAIL}")
    print("\n⚠️  Make sure:")
    print("  1. The server is running (uvicorn app.main:app)")
    print("  2. Test user exists with correct password")
    print("  3. RATE_LIMIT_ENABLED=true in .env")

    input("\nPress Enter to start tests...")

    # Test 1: Login
    access_token, refresh_token = test_login()

    if not access_token or not refresh_token:
        print("\n✗ Cannot continue tests without valid tokens")
        print("  Please ensure test user exists and credentials are correct")
        return

    # Test 2: Refresh
    new_access_token = test_refresh(refresh_token)

    if not new_access_token:
        print("\n✗ Refresh token test failed")

    # Test 3: Login Rate Limiting
    input("\nPress Enter to test login rate limiting (will make 6 requests)...")
    test_login_rate_limit()

    # Test 4: Refresh Rate Limiting
    input("\nPress Enter to test refresh rate limiting (will make 12 requests)...")
    test_refresh_rate_limit(refresh_token)

    print_section("TESTS COMPLETED")
    print("\n✓ All features have been tested!")
    print("\nNote: If rate limiting didn't trigger, check:")
    print("  - RATE_LIMIT_ENABLED=true in .env")
    print("  - Server was restarted after configuration changes")


if __name__ == "__main__":
    main()
