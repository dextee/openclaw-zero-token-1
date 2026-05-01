"""HTTP Basic auth dependency for the SG portal."""

import hashlib
import hmac
import os
import secrets
from datetime import date

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic()
_ph = PasswordHasher()

PORTAL_USERNAME = os.environ.get("PORTAL_USERNAME", "admin")
PORTAL_PASSWORD_HASH = os.environ.get("PORTAL_PASSWORD_HASH", "")
_CSRF_SECRET = os.environ.get("PORTAL_CSRF_SECRET", secrets.token_hex(32))


def require_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    username_ok = secrets.compare_digest(credentials.username, PORTAL_USERNAME)

    password_ok = False
    if PORTAL_PASSWORD_HASH:
        try:
            password_ok = _ph.verify(PORTAL_PASSWORD_HASH, credentials.password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            password_ok = False
    else:
        password_ok = False

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def hash_password(password: str) -> str:
    return _ph.hash(password)


def get_csrf_token() -> str:
    """Return a CSRF token valid for today (rotates daily)."""
    today = date.today().isoformat()
    return hmac.new(_CSRF_SECRET.encode(), today.encode(), hashlib.sha256).hexdigest()[:32]


def verify_csrf_token(token: str) -> bool:
    """Verify a submitted CSRF token."""
    expected = get_csrf_token()
    return secrets.compare_digest(token, expected)
