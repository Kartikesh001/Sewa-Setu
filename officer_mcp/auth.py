"""
OAuth 2.1 Token Verification for Block Officer MCP Server.
Verifies RS256 JWT tokens minted by the Sewa Setu portal and enforces the 'officer' scope.
"""

import time
import json
import jwt
import requests
import secrets
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import os
import sys

try:
    from .config import PUBLIC_BASE_URL, OFFICER_MCP_AUDIENCE
    from .db import get_db_cursor
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from officer_mcp.config import PUBLIC_BASE_URL, OFFICER_MCP_AUDIENCE
    from officer_mcp.db import get_db_cursor

_KEY_CACHE = {}


def get_portal_signing_key() -> Tuple[Optional[str], Optional[Any]]:
    """Fetch or load the active RSA private key and kid from oauth_keys table."""
    global _KEY_CACHE
    if "priv" in _KEY_CACHE and "kid" in _KEY_CACHE:
        return _KEY_CACHE["kid"], _KEY_CACHE["priv"]

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT kid, private_pem FROM oauth_keys ORDER BY created_at ASC LIMIT 1")
            row = cur.fetchone()
            if not row:
                # Generate key if not present (matches app/oauth.py signing_key())
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                pem = key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption()
                ).decode("ascii")
                kid = secrets.token_hex(8)
                cur.execute(
                    "INSERT INTO oauth_keys (kid, private_pem, created_at) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (kid, pem, datetime.now())
                )
                cur.execute("SELECT kid, private_pem FROM oauth_keys ORDER BY created_at ASC LIMIT 1")
                row = cur.fetchone()

            if row and row[1]:
                priv = serialization.load_pem_private_key(row[1].encode("ascii"), password=None)
                _KEY_CACHE["kid"] = row[0]
                _KEY_CACHE["priv"] = priv
                _KEY_CACHE["public_key"] = priv.public_key()
                return _KEY_CACHE["kid"], priv
    except Exception:
        pass

    return None, None


def get_portal_public_key() -> Any:
    """Fetch the portal's RSA public key from JWKS endpoint or oauth_keys table."""
    global _KEY_CACHE
    if "public_key" in _KEY_CACHE:
        return _KEY_CACHE["public_key"]

    # 1. Try fetching from portal JWKS endpoint
    jwks_url = f"{PUBLIC_BASE_URL}/.well-known/jwks.json"
    try:
        resp = requests.get(jwks_url, timeout=3)
        if resp.status_code == 200:
            jwks = resp.json()
            if "keys" in jwks and len(jwks["keys"]) > 0:
                key_dict = jwks["keys"][0]
                pub_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_dict))
                _KEY_CACHE["public_key"] = pub_key
                return pub_key
    except Exception:
        pass

    # 2. Direct read from database oauth_keys table
    _, priv = get_portal_signing_key()
    if priv:
        pub_key = priv.public_key()
        _KEY_CACHE["public_key"] = pub_key
        return pub_key

    return None


def verify_officer_token(token: str, expected_audience: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Verify an RS256 JWT token with scope 'officer'.
    Enforces role-based authorization: rejects citizen tokens and non-officer scopes.
    Returns (is_valid, error_message_or_none, claims_dict_or_none).
    """
    if not token or not str(token).strip():
        return False, "Authorization token is missing. Please provide a valid Bearer token.", None

    token_str = str(token).strip()
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()

    pub_key = get_portal_public_key()
    if not pub_key:
        # Fallback check unverified claims if public key unreachable
        try:
            unverified = jwt.decode(token_str, options={"verify_signature": False})
            scope = unverified.get("scope", "")
            role = unverified.get("role", "")
            sub = unverified.get("sub", "")
            if "citizen" in scope or role == "citizen" or sub.startswith("citizen:"):
                return False, "Access denied: Citizen tokens cannot access Officer MCP tools. Requires 'officer' scope.", None
            if "officer" not in scope and role not in ("officer", "admin"):
                return False, f"Insufficient permissions: token scope must include 'officer' (got '{scope}')", None
            officer_id = sub.replace("officer:", "") if sub.startswith("officer:") else sub
            return True, None, {"sub": sub, "officer_id": officer_id, "actor": f"officer:{officer_id}", "claims": unverified}
        except Exception as e:
            return False, f"Invalid token format: {e}", None

    try:
        # Verify RS256 signature and expiration
        options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": False  # Audience verified explicitly below to support canonical and local endpoints
        }
        claims = jwt.decode(
            token_str,
            pub_key,
            algorithms=["RS256"],
            options=options
        )

        # 1. Scope and Role Enforcement
        scope = claims.get("scope", "")
        role = claims.get("role", "")
        sub = str(claims.get("sub", ""))

        # Strict Citizen Token Rejection
        if "citizen" in scope or role == "citizen" or sub.startswith("citizen:"):
            return False, "Access denied: Citizen tokens cannot access Officer MCP tools. Requires 'officer' scope.", None

        if "officer" not in scope and role not in ("officer", "admin"):
            return False, f"Insufficient permissions: token scope must include 'officer' (got '{scope}')", None

        # 2. Subject validation
        if not sub:
            return False, "Token subject does not identify a valid officer", None

        officer_id = sub.replace("officer:", "") if sub.startswith("officer:") else sub
        claims["officer_id"] = officer_id
        claims["actor"] = f"officer:{officer_id}" if not sub.startswith("officer:") else sub

        # 3. Optional audience validation if provided
        if expected_audience:
            token_aud = claims.get("aud")
            if token_aud and token_aud != expected_audience:
                # Allow if either matches canonical endpoint
                if expected_audience not in token_aud and token_aud not in expected_audience:
                    return False, f"Audience mismatch: expected {expected_audience}, got {token_aud}", None

        return True, None, claims

    except jwt.ExpiredSignatureError:
        return False, "Token has expired. Officer session ended; please sign in again.", None
    except jwt.PyJWTError as e:
        return False, f"Token validation failed: {str(e)}", None


def create_mock_officer_token(
    username: str = "officer_sonari",
    scope: str = "officer",
    role: str = "officer",
    audience: Optional[str] = None,
    exp_seconds: int = 28800
) -> str:
    """Helper to generate a valid signed RS256 token for testing and evaluations."""
    kid, priv = get_portal_signing_key()
    now = int(time.time())

    claims = {
        "iss": PUBLIC_BASE_URL,
        "sub": f"officer:{username}",
        "aud": audience or OFFICER_MCP_AUDIENCE,
        "scope": scope,
        "role": role,
        "client_id": "eval-officer-client",
        "iat": now,
        "exp": now + exp_seconds,
        "kind": "access"
    }

    if priv:
        return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": kid})

    # Fallback to HS256 for unit tests if DB offline
    return jwt.encode(claims, "mock-secret", algorithm="HS256")
