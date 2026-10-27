"""Common HTTP Basic authentication for every API (public /api/*, internal /internal/*).

One credential pair (API_USERNAME / API_PASSWORD) is shared by the React app, Boomi and this service.
Fails closed: if the credentials are not configured, every protected call is refused with 503.
"""
from __future__ import annotations

import base64
import binascii
import hmac

from fastapi import HTTPException, Request

from .config import get_settings


def _challenge(request: Request) -> dict[str, str]:
    # Only machine callers (Boomi) get the browser-popup challenge; the React app handles 401 itself.
    return {"WWW-Authenticate": 'Basic realm="atom-foundry", charset="UTF-8"'} if request.url.path.startswith("/internal") else {}


def require_basic(request: Request) -> str:
    s = get_settings()
    if not s.api_username or not s.api_password:
        raise HTTPException(503, "API credentials are not configured on the server (set API_USERNAME and API_PASSWORD).")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        raise HTTPException(401, "Authentication required.", headers=_challenge(request))
    try:
        user, _, password = base64.b64decode(token.strip(), validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(401, "Invalid credentials.", headers=_challenge(request))
    ok_user = hmac.compare_digest(user.encode(), s.api_username.encode())
    ok_pass = hmac.compare_digest(password.encode(), s.api_password.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(401, "Invalid credentials.", headers=_challenge(request))
    return user
