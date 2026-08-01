"""Bounded retries, stable error codes, and run-level budgets."""

from __future__ import annotations

import json
import errno
import socket
import time
import urllib.error
from dataclasses import asdict
from typing import Any, Callable, TypeVar

from .models import BudgetUsage


T = TypeVar("T")
TRANSIENT_HTTP_STATUSES = {408, 429}


def _is_transient_status(status: int) -> bool:
    return status in TRANSIENT_HTTP_STATUSES or 500 <= status <= 599


class ExecutionCallError(RuntimeError):
    """A sanitized wrapper retaining only the original exception in memory."""

    def __init__(self, cause: Exception, attempts: int) -> None:
        super().__init__(stable_error_code(cause))
        self.cause = cause
        self.attempts = attempts


class BudgetExhausted(RuntimeError):
    def __init__(self, limit: str) -> None:
        super().__init__(f"budget_exhausted:{limit}")
        self.limit = limit


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return None


def is_transient_error(exc: Exception) -> bool:
    status = _status_code(exc)
    if status is not None:
        return _is_transient_status(status)
    if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return _is_transient_network_reason(exc.reason)
    # Avoid importing an optional provider SDK merely to classify its errors.
    return exc.__class__.__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }


def _is_transient_network_reason(reason: object) -> bool:
    if isinstance(reason, (TimeoutError, ConnectionError, socket.timeout)):
        return True
    if isinstance(reason, socket.gaierror):
        return reason.errno == getattr(socket, "EAI_AGAIN", None)
    if isinstance(reason, OSError):
        return reason.errno in {
            errno.ECONNABORTED,
            errno.ECONNREFUSED,
            errno.ECONNRESET,
            errno.EHOSTUNREACH,
            errno.ENETDOWN,
            errno.ENETUNREACH,
            errno.EPIPE,
            errno.ETIMEDOUT,
        }
    return False


def stable_error_code(exc: Exception) -> str:
    if isinstance(exc, ExecutionCallError):
        return stable_error_code(exc.cause)
    status = _status_code(exc)
    if status in {401, 403}:
        return "authentication_failed"
    if status == 429:
        return "rate_limited"
    if status is not None and _is_transient_status(status):
        return "provider_unavailable"
    if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout, urllib.error.URLError)):
        return "provider_unavailable"
    if isinstance(exc, (json.JSONDecodeError, TypeError, ValueError, KeyError)):
        return "invalid_model_response"
    if exc.__class__.__name__ in {"AuthenticationError", "PermissionDeniedError"}:
        return "authentication_failed"
    if exc.__class__.__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }:
        return "provider_unavailable"
    return "provider_error"


def call_with_retries(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    initial_delay_seconds: float = 0.5,
    max_delay_seconds: float = 4.0,
    before_attempt: Callable[[], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Run an operation at most three times, and only retry transient errors."""

    attempts_limit = max(1, min(3, int(max_attempts)))
    for attempt in range(1, attempts_limit + 1):
        if before_attempt:
            before_attempt()
        try:
            return operation(), attempt
        except BudgetExhausted:
            raise
        except Exception as exc:
            if not is_transient_error(exc) or attempt >= attempts_limit:
                raise ExecutionCallError(exc, attempt) from exc
            delay = min(max_delay_seconds, initial_delay_seconds * (2 ** (attempt - 1)))
            sleeper(max(0.0, delay))
    raise AssertionError("retry loop must return or raise")


class BudgetTracker:
    """Strictly enforce configured total counters for one run."""

    COUNTERS = {
        "max_sources_total": "sources_total",
        "max_items_total": "items_total",
        "max_provider_attempts_total": "provider_attempts_total",
        "max_input_chars_total": "input_chars_total",
        "max_output_tokens_total": "output_tokens_total",
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        raw = config or {}
        self.started_at = time.monotonic()
        self.limits: dict[str, int | float | None] = {}
        for limit_name in self.COUNTERS:
            value = raw.get(limit_name)
            self.limits[limit_name] = int(value) if value is not None else None
        elapsed_limit = raw.get("max_elapsed_seconds")
        self.limits["max_elapsed_seconds"] = (
            float(elapsed_limit) if elapsed_limit is not None else None
        )
        self.used = {counter: 0 for counter in self.COUNTERS.values()}
        self.used["elapsed_seconds"] = 0
        self.status = "within_limit"
        self.exhausted_limit: str | None = None

    def consume(self, limit_name: str, amount: int = 1) -> None:
        self.check_elapsed()
        if limit_name not in self.COUNTERS:
            raise KeyError(limit_name)
        amount = max(0, int(amount))
        counter = self.COUNTERS[limit_name]
        limit = self.limits[limit_name]
        if limit is not None and self.used[counter] + amount > limit:
            self.status = "exhausted"
            self.exhausted_limit = limit_name
            raise BudgetExhausted(limit_name)
        self.used[counter] += amount

    def reserve_provider_attempt(self, input_chars: int, output_tokens: int) -> None:
        self.check_elapsed()
        # Check every counter before consuming any, so a rejected attempt is
        # observable but never partially charged to run usage.
        requested = {
            "max_provider_attempts_total": 1,
            "max_input_chars_total": max(0, input_chars),
            "max_output_tokens_total": max(0, output_tokens),
        }
        for limit_name, amount in requested.items():
            counter = self.COUNTERS[limit_name]
            limit = self.limits[limit_name]
            if limit is not None and self.used[counter] + amount > limit:
                self.status = "exhausted"
                self.exhausted_limit = limit_name
                raise BudgetExhausted(limit_name)
        for limit_name, amount in requested.items():
            self.used[self.COUNTERS[limit_name]] += amount

    def check_elapsed(self) -> None:
        elapsed = max(0.0, time.monotonic() - self.started_at)
        self.used["elapsed_seconds"] = elapsed
        limit = self.limits.get("max_elapsed_seconds")
        if limit is not None and elapsed >= limit:
            self.status = "exhausted"
            self.exhausted_limit = "max_elapsed_seconds"
            raise BudgetExhausted("max_elapsed_seconds")

    def remaining_seconds(self) -> float | None:
        limit = self.limits.get("max_elapsed_seconds")
        if limit is None:
            return None
        elapsed = max(0.0, time.monotonic() - self.started_at)
        self.used["elapsed_seconds"] = elapsed
        remaining = float(limit) - elapsed
        if remaining <= 0:
            self.status = "exhausted"
            self.exhausted_limit = "max_elapsed_seconds"
            raise BudgetExhausted("max_elapsed_seconds")
        return remaining

    def bounded_timeout(self, configured_seconds: float) -> float:
        configured = float(configured_seconds)
        if configured <= 0:
            raise ValueError("request timeout must be positive")
        remaining = self.remaining_seconds()
        timeout = configured if remaining is None else min(configured, remaining)
        # Do not start external work with a deadline too small for the runtime
        # to represent or enforce meaningfully.
        if timeout < 0.001:
            self.status = "exhausted"
            self.exhausted_limit = "max_elapsed_seconds"
            raise BudgetExhausted("max_elapsed_seconds")
        return timeout

    def snapshot(self) -> BudgetUsage:
        elapsed = max(0.0, time.monotonic() - self.started_at)
        self.used["elapsed_seconds"] = elapsed
        elapsed_limit = self.limits.get("max_elapsed_seconds")
        if elapsed_limit is not None and elapsed >= elapsed_limit:
            self.status = "exhausted"
            self.exhausted_limit = "max_elapsed_seconds"
        return BudgetUsage(
            limits=dict(self.limits),
            used=dict(self.used),
            status=self.status,
            exhausted_limit=self.exhausted_limit,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.snapshot())
