"""Cryptographic Security, Token Engine & RBAC Enforcement for SongNhat CRM Review Workflow.

Sub-milestone: P2.4.7 / Security Foundation
Module: backend.review.security

Key Capabilities:
1. Salted Cryptographic Password Hashing via PBKDF2-HMAC-SHA256 (100,000 iterations).
2. Standard HMAC-SHA256 JWT Token Issuance & Verification (Zero external dependencies).
3. Maker-Checker Dual Control Enforcement (`proposer <> approver`).
4. Role-Based Access Control (RBAC) Permission Resolution.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID

from fastapi import Depends, HTTPException, Header, status
from pydantic import BaseModel, Field

# Secret key for JWT signing (can be overridden via environment variable)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "songnhat-crm-maker-checker-dual-control-secret-key-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8
PBKDF2_ITERATIONS = 100_000


class UserContext(BaseModel):
    """Authenticated user context containing identity, assigned roles and permissions."""

    user_id: str
    username: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    def has_role(self, role: str) -> bool:
        return role.upper() in [r.upper() for r in self.roles]

    def has_permission(self, permission: str) -> bool:
        if self.has_role("ADMINISTRATOR") or "ADMIN_ALL" in self.permissions:
            return True
        return permission.upper() in [p.upper() for p in self.permissions]


# ---------------------------------------------------------------------------
# 1. Cryptographic Password Hashing (PBKDF2-HMAC-SHA256)
# ---------------------------------------------------------------------------

def get_password_hash(password: str) -> str:
    """Hash password using salted PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    salt_hex = salt.hex()
    hash_hex = dk.hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_hex}${hash_hex}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against PBKDF2-HMAC-SHA256 hash in constant time."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_hash = bytes.fromhex(parts[3])

        computed_hash = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(computed_hash, expected_hash)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 2. Standard HMAC-SHA256 JWT Token Implementation
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (4 - (len(s) % 4)) if len(s) % 4 != 0 else ""
    return base64.urlsafe_b64decode(s + padding)


def create_access_token(
    user_id: Union[str, UUID],
    username: str,
    roles: Optional[List[str]] = None,
    permissions: Optional[List[str]] = None,
    expires_in_hours: int = JWT_EXPIRATION_HOURS,
) -> str:
    """Generate cryptographically signed JWT token with identity, roles, and permissions."""
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    now_ts = int(time.time())
    exp_ts = now_ts + (expires_in_hours * 3600)

    payload = {
        "sub": str(user_id),
        "username": username,
        "roles": roles or [],
        "permissions": permissions or [],
        "iat": now_ts,
        "exp": exp_ts,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    sig = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Verify JWT token signature and expiration, returning decoded payload."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT token format.")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    expected_sig = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("JWT token signature verification failed.")

    payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    exp = payload.get("exp")
    if exp and int(time.time()) > exp:
        raise ValueError("JWT token has expired.")

    return payload


# ---------------------------------------------------------------------------
# 3. Dual Control (Maker-Checker) Enforcement Guardrail
# ---------------------------------------------------------------------------

def verify_independent_approver(proposer_id: Union[str, UUID], approver_id: Union[str, UUID]) -> bool:
    """
    Enforce Maker-Checker Dual Control constraint (REV 03 / BR-10 / SEC 01).
    Proposer and Approver MUST be strictly different identities.
    Returns True if valid (independent); False if self-approval attempt or invalid.
    """
    if not proposer_id or not approver_id:
        return False

    str_proposer = str(proposer_id).strip().lower()
    str_approver = str(approver_id).strip().lower()

    if not str_proposer or not str_approver:
        return False

    return str_proposer != str_approver


# ---------------------------------------------------------------------------
# 4. FastAPI Dependency Injections for Authentication & RBAC
# ---------------------------------------------------------------------------

def get_current_user(authorization: Optional[str] = Header(None)) -> UserContext:
    """Extract and validate authenticated UserContext from Authorization Bearer header."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserContext(
        user_id=payload["sub"],
        username=payload["username"],
        roles=payload.get("roles", []),
        permissions=payload.get("permissions", []),
    )


def require_role(role_name: str):
    """FastAPI dependency factory enforcing that current user possesses specified role."""
    def dependency(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not user.has_role(role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Required role '{role_name}' is missing.",
            )
        return user
    return dependency


def require_permission(permission_code: str):
    """FastAPI dependency factory enforcing that current user possesses specified permission."""
    def dependency(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not user.has_permission(permission_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Required permission '{permission_code}' is missing.",
            )
        return user
    return dependency
