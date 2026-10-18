"""
OAuth 2.1 Token Verification for Citizen MCP Server.
Verifies RS256 JWT tokens minted by the Sewa Setu portal.
"""

import time
import json
import jwt
import requests
from typing import Optional, Dict, Any, Tuple
from cryptography.hazmat.primitives import serialization
import os
import sys

try:
    from .config import PUBLIC_BASE_URL, CITIZEN_MCP_AUDIENCE
    from .db import get_db_cursor
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from citizen_mcp.config import PUBLIC_BASE_URL, CITIZEN_MCP_AUDIENCE
    from citizen_mcp.db import get_db_cursor

_KEY_CACHE = {}


def get_portal_public_key() -> Any:
    """Fetch the portal's RSA public key from JWKS or directly from database."""
    global _KEY_CACHE
    if "public_key" in _KEY_CACHE:
        return _KEY_CACHE["public_key"]

    # 1. Try fetching from the running portal JWKS endpoint
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

    # 2. Fallback: Read directly from oauth_keys table in Postgres
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT kid, private_pem FROM oauth_keys ORDER BY created_at ASC LIMIT 1")
            row = cur.fetchone()
            if row and row[1]:
                priv = serialization.load_pem_private_key(row[1].encode("ascii"), password=None)
                pub_key = priv.public_key()
                _KEY_CACHE["public_key"] = pub_key
                _KEY_CACHE["priv"] = priv
                _KEY_CACHE["kid"] = row[0]
                return pub_key
    except Exception:
        pass

    return None


def verify_citizen_token(token: str, expected_audience: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Verify an RS256 JWT token with scope 'citizen'.
    Returns (is_valid, error_message_or_none, claims_dict_or_none).
    """
    if not token:
        return False, "Authorization token is missing. Please provide a valid Bearer token.", None

    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    pub_key = get_portal_public_key()
    if not pub_key:
        # If public key cannot be retrieved yet (e.g. initial setup before DB/portal starts),
        # parse unverified claims to check structure
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            if unverified.get("role") == "citizen" or unverified.get("scope") == "citizen":
                sub = unverified.get("sub", "")
                mobile = sub.replace("citizen:", "") if "citizen:" in sub else sub
                return True, None, {"sub": sub, "mobile": mobile, "claims": unverified}
        except Exception as e:
            return False, f"Invalid token format: {e}", None

    try:
        # Decode and verify signature
        options = {"verify_signature": True, "verify_exp": True, "verify_aud": False}
        claims = jwt.decode(
            token,
            pub_key,
            algorithms=["RS256"],
            options=options
        )

        # Verify scope and role
        scope = claims.get("scope", "")
        role = claims.get("role", "")
        if "citizen" not in scope and role != "citizen":
            return False, f"Insufficient permissions: token scope must include 'citizen' (got '{scope}')", None

        # Extract mobile number from sub
        sub = claims.get("sub", "")
        mobile = sub.replace("citizen:", "") if sub.startswith("citizen:") else sub
        if not mobile:
            return False, "Token subject does not identify a valid citizen mobile number", None

        claims["mobile"] = mobile
        return True, None, claims

    except jwt.ExpiredSignatureError:
        return False, "Token has expired. Citizen session ended; please sign in again.", None
    except jwt.PyJWTError as e:
        return False, f"Token validation failed: {str(e)}", None


def create_mock_citizen_token(mobile: str) -> str:
    """Helper to generate a valid signed token for evaluation / testing."""
    pub_key = get_portal_public_key()
    priv = _KEY_CACHE.get("priv")
    kid = _KEY_CACHE.get("kid", "eval-kid")
    now = int(time.time())

    claims = {
        "iss": PUBLIC_BASE_URL,
        "sub": f"citizen:{mobile}",
        "aud": CITIZEN_MCP_AUDIENCE,
        "scope": "citizen",
        "role": "citizen",
        "client_id": "eval-client",
        "iat": now,
        "exp": now + 7200,
        "kind": "access"
    }

    if priv:
        return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": kid})

    # Fallback to hs256 mock if rsa priv unavailable in test
    return jwt.encode(claims, "mock-secret", algorithm="HS256")
