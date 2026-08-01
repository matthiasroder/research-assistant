import errno
import ssl
import unittest
import urllib.error
from unittest import mock

from research_platform.execution import (
    BudgetExhausted,
    BudgetTracker,
    ExecutionCallError,
    call_with_retries,
)


class RetryTests(unittest.TestCase):
    def test_transient_timeout_retries_but_never_more_than_three(self):
        operation = mock.Mock(side_effect=TimeoutError("down"))
        with self.assertRaises(ExecutionCallError) as caught:
            call_with_retries(operation, max_attempts=99, sleeper=lambda _delay: None)
        self.assertEqual(operation.call_count, 3)
        self.assertEqual(caught.exception.attempts, 3)

    def test_authentication_failure_is_not_retried(self):
        error = urllib.error.HTTPError("https://example.com", 401, "unauthorized", {}, None)
        operation = mock.Mock(side_effect=error)
        with self.assertRaises(ExecutionCallError):
            call_with_retries(operation, sleeper=lambda _delay: None)
        self.assertEqual(operation.call_count, 1)

    def test_any_5xx_status_is_retryable(self):
        error = urllib.error.HTTPError("https://example.com", 501, "unavailable", {}, None)
        operation = mock.Mock(side_effect=[error, "ok"])
        value, attempts = call_with_retries(operation, sleeper=lambda _delay: None)
        self.assertEqual(value, "ok")
        self.assertEqual(attempts, 2)

    def test_schema_failure_is_not_retried(self):
        operation = mock.Mock(side_effect=ValueError("bad response"))
        with self.assertRaises(ExecutionCallError):
            call_with_retries(operation, sleeper=lambda _delay: None)
        self.assertEqual(operation.call_count, 1)

    def test_tls_certificate_failure_wrapped_by_urlerror_is_not_retried(self):
        error = urllib.error.URLError(
            ssl.SSLCertVerificationError(1, "certificate verify failed")
        )
        operation = mock.Mock(side_effect=error)
        with self.assertRaises(ExecutionCallError):
            call_with_retries(operation, sleeper=lambda _delay: None)
        self.assertEqual(operation.call_count, 1)

    def test_nontransient_oserror_wrapped_by_urlerror_is_not_retried(self):
        error = urllib.error.URLError(OSError(errno.EINVAL, "invalid argument"))
        operation = mock.Mock(side_effect=error)
        with self.assertRaises(ExecutionCallError):
            call_with_retries(operation, sleeper=lambda _delay: None)
        self.assertEqual(operation.call_count, 1)

    def test_connection_reset_wrapped_by_urlerror_is_retried(self):
        error = urllib.error.URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        operation = mock.Mock(side_effect=[error, "ok"])
        value, attempts = call_with_retries(operation, sleeper=lambda _delay: None)
        self.assertEqual(value, "ok")
        self.assertEqual(attempts, 2)


class BudgetTrackerTests(unittest.TestCase):
    def test_provider_reservation_is_all_or_none(self):
        budget = BudgetTracker(
            {
                "max_provider_attempts_total": 1,
                "max_input_chars_total": 10,
                "max_output_tokens_total": 5,
            }
        )
        with self.assertRaises(BudgetExhausted):
            budget.reserve_provider_attempt(11, 5)
        usage = budget.snapshot()
        self.assertEqual(usage.status, "exhausted")
        self.assertEqual(usage.used["provider_attempts_total"], 0)
        self.assertEqual(usage.used["input_chars_total"], 0)

    def test_elapsed_limit_is_exposed(self):
        budget = BudgetTracker({"max_elapsed_seconds": 1})
        with mock.patch("research_platform.execution.time.monotonic", return_value=budget.started_at + 2):
            with self.assertRaises(BudgetExhausted):
                budget.check_elapsed()
        self.assertEqual(budget.snapshot().exhausted_limit, "max_elapsed_seconds")

    def test_elapsed_limit_exhausts_at_exact_float_boundary(self):
        budget = BudgetTracker({"max_elapsed_seconds": 1.25})
        with mock.patch(
            "research_platform.execution.time.monotonic",
            return_value=budget.started_at + 1.25,
        ):
            with self.assertRaises(BudgetExhausted):
                budget.check_elapsed()
            snapshot = budget.snapshot()
        self.assertEqual(snapshot.used["elapsed_seconds"], 1.25)
        self.assertEqual(snapshot.exhausted_limit, "max_elapsed_seconds")

    def test_request_timeout_is_bounded_by_remaining_elapsed_budget(self):
        budget = BudgetTracker({"max_elapsed_seconds": 10.0})
        with mock.patch(
            "research_platform.execution.time.monotonic",
            return_value=budget.started_at + 8.5,
        ):
            self.assertAlmostEqual(budget.bounded_timeout(30), 1.5)

    def test_tiny_remaining_budget_prevents_external_work(self):
        budget = BudgetTracker({"max_elapsed_seconds": 10.0})
        with mock.patch(
            "research_platform.execution.time.monotonic",
            return_value=budget.started_at + 9.9995,
        ):
            with self.assertRaises(BudgetExhausted):
                budget.bounded_timeout(30)


if __name__ == "__main__":
    unittest.main()
