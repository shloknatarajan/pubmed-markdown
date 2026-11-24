"""Tests for shared HTTP utilities: WAF detection, Retry-After parsing, and retries."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from pubmed_markdown.http_utils import (
    WAFChallengeError,
    compute_backoff,
    get_with_retries,
    is_waf_or_captcha_html,
    parse_retry_after,
)

# ---------------------------------------------------------------------------
# WAF / CAPTCHA detection
# ---------------------------------------------------------------------------


def test_detects_aws_waf_recaptcha_page():
    waf_html = """<!DOCTYPE html>
    <html>
    <head><title>Checking your browser - reCAPTCHA</title></head>
    <body><div id="captcha-container">Please verify you are human</div></body>
    </html>"""
    assert is_waf_or_captcha_html(waf_html) is True


def test_detects_aws_waf_script_challenge():
    waf_html = """<html><head><title>Verify</title></head>
    <body><script src="https://abc123.challenge.awswaf.com/challenge.js"></script></body></html>"""
    assert is_waf_or_captcha_html(waf_html) is True


def test_detects_403_forbidden_html_stub():
    html = "<html><head><title>403 Forbidden</title></head><body><h1>403 Forbidden</h1></body></html>"
    assert is_waf_or_captcha_html(html) is True


def test_legitimate_pmc_article_mentioning_recaptcha_not_flagged():
    """A real PMC article discussing reCAPTCHA should not trigger a false positive."""
    article_html = """<html>
    <head>
        <meta name="citation_title" content="Usability of reCAPTCHA in Clinical Portals">
    </head>
    <body>
        <section class="main-article-body">
            <section id="sec1">
                <h2 class="pmc_sec_title">Introduction</h2>
                <p>Users encountered "Checking your browser" and g-recaptcha prompts.</p>
            </section>
        </section>
    </body>
    </html>"""
    assert is_waf_or_captcha_html(article_html) is False


def test_normal_minimal_html_not_flagged():
    assert is_waf_or_captcha_html("<html><body>Article content</body></html>") is False
    assert is_waf_or_captcha_html("<html></html>") is False
    assert is_waf_or_captcha_html("") is False


# ---------------------------------------------------------------------------
# Retry-After parsing & backoff
# ---------------------------------------------------------------------------


def test_parse_retry_after_numeric():
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("2.5") == 2.5
    assert parse_retry_after("120", max_wait=60.0) == 60.0
    assert parse_retry_after("-3") == 0.0


def test_parse_retry_after_http_date():
    future = datetime.now(timezone.utc) + timedelta(seconds=10)
    header = format_datetime(future, usegmt=True)
    delay = parse_retry_after(header, max_wait=60.0)
    assert delay is not None
    assert 5.0 <= delay <= 12.0


def test_parse_retry_after_invalid():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-date") is None


def test_compute_backoff_prefers_retry_after():
    assert compute_backoff(0, backoff_factor=1.0, retry_after="7") == 7.0


# ---------------------------------------------------------------------------
# get_with_retries
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.http_utils.time.sleep")
def test_retries_on_429_with_retry_after(mock_sleep):
    resp_429 = MagicMock(status_code=429, headers={"Retry-After": "3"})
    resp_200 = MagicMock(status_code=200, headers={}, text="ok")
    request_fn = MagicMock(side_effect=[resp_429, resp_200])

    resp = get_with_retries(
        "https://example.com", request_fn=request_fn, timeout=15.0, max_retries=2
    )
    assert resp is resp_200
    assert request_fn.call_count == 2
    assert request_fn.call_args.kwargs["timeout"] == 15.0
    mock_sleep.assert_called_once_with(3.0)


@patch("pubmed_markdown.http_utils.time.sleep")
def test_retries_on_503_then_succeeds(mock_sleep):
    resp_503 = MagicMock(status_code=503, headers={})
    resp_200 = MagicMock(status_code=200, headers={}, text="ok")
    request_fn = MagicMock(side_effect=[resp_503, resp_200])

    resp = get_with_retries("https://example.com", request_fn=request_fn, max_retries=2)
    assert resp is resp_200
    assert request_fn.call_count == 2
    assert mock_sleep.call_count == 1


@patch("pubmed_markdown.http_utils.time.sleep")
def test_does_not_retry_on_403_or_404(mock_sleep):
    for status in (403, 404):
        resp_err = MagicMock(status_code=status, headers={})
        request_fn = MagicMock(return_value=resp_err)

        resp = get_with_retries(
            "https://example.com", request_fn=request_fn, max_retries=2
        )
        assert resp is resp_err
        assert request_fn.call_count == 1
        mock_sleep.assert_not_called()


@patch("pubmed_markdown.http_utils.time.sleep")
def test_retries_on_timeout_then_succeeds(mock_sleep):
    resp_200 = MagicMock(status_code=200, headers={}, text="ok")
    request_fn = MagicMock(
        side_effect=[requests.exceptions.Timeout("timed out"), resp_200]
    )

    resp = get_with_retries("https://example.com", request_fn=request_fn, max_retries=2)
    assert resp is resp_200
    assert request_fn.call_count == 2
    assert mock_sleep.call_count == 1


@patch("pubmed_markdown.http_utils.time.sleep")
def test_validation_failure_retries_and_raises_waf_error(mock_sleep):
    resp_waf = MagicMock(status_code=200, headers={}, text="Checking your browser")
    request_fn = MagicMock(return_value=resp_waf)

    with pytest.raises(WAFChallengeError, match="WAF detected"):
        get_with_retries(
            "https://example.com",
            request_fn=request_fn,
            max_retries=2,
            validate_response=lambda r: "WAF detected",
        )

    assert request_fn.call_count == 3
    assert mock_sleep.call_count == 2
