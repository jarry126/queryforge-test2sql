"""异常分类器单测（纯逻辑）。"""

import pytest

from app.core.errors import AppError, classify, friendly_answer


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHTTPError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.response = _FakeResp(status_code)


def test_rate_limit_by_status():
    err = classify(_FakeHTTPError(429))
    assert err.status_code == 429 and err.category == "rate_limited"


def test_rate_limit_by_message():
    err = classify(Exception("Throttling.RateQuota: too many requests"))
    assert err.status_code == 429


def test_upstream_by_5xx():
    assert classify(_FakeHTTPError(503)).status_code == 503


@pytest.mark.parametrize("msg", ["connection refused", "request timed out", "circuit breaker open"])
def test_upstream_by_message(msg):
    assert classify(Exception(msg)).status_code == 503


def test_unknown_is_500():
    err = classify(ValueError("某个莫名其妙的 bug"))
    assert err.status_code == 500 and err.category == "internal_error"


def test_apperror_passthrough():
    e = AppError(429, "rate_limited", "慢点")
    assert classify(e) is e


def test_friendly_answer_has_request_id():
    msg = friendly_answer(Exception("boom"), "abc123")
    assert "abc123" in msg
