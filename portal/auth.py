"""HTTP Basic auth dependency for the SG portal."""

import hashlib
import hmac
import os
import secrets
from collections import defaultdict
from datetime import date
from time import monotonic

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic()
_ph = PasswordHasher()

PORTAL_USERNAME = os.environ.get("PORTAL_USERNAME", "admin")
PORTAL_PASSWORD_HASH = os.environ.get("PORTAL_PASSWORD_HASH", "")
_CSRF_SECRET = os.environ.get("PORTAL_CSRF_SECRET", secrets.token_hex(32))

_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_WINDOW = 300.0   # 5-minute window
_LOGIN_MAX = 10          # max attempts before lockout


def require_auth(request: Request, credentials: HTTPBasicCredentials = Depends(_security)):
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
        client_ip = request.client.host if request.client else "unknown"
        now = monotonic()
        _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now - t < _LOGIN_WINDOW]
        if len(_login_attempts[client_ip]) >= _LOGIN_MAX:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 5 minutes.")
        _login_attempts[client_ip].append(now)
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
