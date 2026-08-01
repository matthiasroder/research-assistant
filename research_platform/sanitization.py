"""Artifact-safe recursive sanitization for source and item metadata."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SENSITIVE_EXACT_KEYS = {
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "header",
    "headers",
    "key",
    "password",
    "passwd",
    "passcode",
    "passphrase",
    "provider_record",
    "pwd",
    "request",
    "request_headers",
    "session",
    "sig",
    "signature",
    "secret",
    "token",
}
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "accesskey",
    "authcode",
    "authentication",
    "authtoken",
    "authorization",
    "cookie",
    "credential",
    "header",
    "password",
    "passcode",
    "passphrase",
    "passwd",
    "provider_record",
    "request",
    "secret",
    "token",
)
_SENSITIVE_KEY_SEGMENTS = {
    "auth",
    "authentication",
    "authorization",
    "bearer",
    "credential",
    "key",
    "oauth",
    "oauth2",
    "passcode",
    "passphrase",
    "passwd",
    "password",
    "pwd",
    "secret",
    "sig",
    "signature",
    "token",
}
_EMBEDDED_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
    segments = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return (
        normalized in _SENSITIVE_EXACT_KEYS
        or bool(segments & _SENSITIVE_KEY_SEGMENTS)
        or any(
        part in normalized for part in _SENSITIVE_KEY_PARTS
        )
        or any(
            part in compact
            for part in (
                "accesskey",
                "apikey",
                "authcode",
                "authentication",
                "authorization",
                "authtoken",
                "credential",
                "passcode",
                "passphrase",
                "passwd",
                "password",
                "secretkey",
                "securitytoken",
                "signature",
            )
        )
    )


def sanitize_url(url: str | None) -> str | None:
    """Remove user info, fragments, and credential-bearing query values."""

    if not url:
        return url
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return url
    # Drop any username/password component without trying to reconstruct it.
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    safe_query = urlencode(
        [
            (key, sanitize_text_urls(value))
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not is_sensitive_key(key)
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, safe_query, ""))


def sanitize_text_urls(value: str) -> str:
    """Sanitize every HTTP(S) URL embedded in otherwise ordinary text."""

    def replace(match: re.Match[str]) -> str:
        sanitized = sanitize_url(match.group(0))
        return sanitized or ""

    return _EMBEDDED_HTTP_URL.sub(replace, value)


def sanitize_artifact_data(value: Any) -> Any:
    """Recursively remove credential containers and sanitize embedded URLs."""

    if isinstance(value, dict):
        return {
            str(key): sanitize_artifact_data(child)
            for key, child in value.items()
            if not is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [sanitize_artifact_data(child) for child in value]
    if isinstance(value, tuple):
        return [sanitize_artifact_data(child) for child in value]
    if isinstance(value, str):
        return sanitize_text_urls(value)
    return value
