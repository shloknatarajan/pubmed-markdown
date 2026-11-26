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


def test_get_http_session_is_reused_per_thread():
    import threading
    from pubmed_markdown.http_utils import get_http_session

    s1 = get_http_session()
    s2 = get_http_session()
    assert s1 is s2
    assert isinstance(s1, requests.Session)

    other = []

    def worker():
        other.append(get_http_session())

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert len(other) == 1
    assert other[0] is not s1


# ---------------------------------------------------------------------------
# HostRateLimiter
# ---------------------------------------------------------------------------


def test_host_rate_limiter_groups_ncbi_and_isolates_europe_pmc():
    from pubmed_markdown.http_utils import HostRateLimiter

    limiter = HostRateLimiter(
        intervals={"ncbi_api": 0.25, "europe_pmc": 0.25, "pmc_html": 0.5}
    )

    with patch("pubmed_markdown.http_utils.time.sleep") as mock_sleep:
        w1 = limiter.acquire(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        )
        # Different host group (Europe PMC) should dispatch immediately
        w_epmc = limiter.acquire(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML"
        )
        # Same host group as eutils (www.ncbi.nlm.nih.gov) should wait
        w2 = limiter.acquire("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/")

    assert w1 == 0.0
    assert w_epmc == 0.0
    assert 0.15 <= w2 <= 0.3
    mock_sleep.assert_called_once()


def test_host_rate_limiter_respects_ncbi_api_key_env(monkeypatch):
    from pubmed_markdown.http_utils import (
        HostRateLimiter,
        NCBI_DEFAULT_MIN_INTERVAL_NO_KEY,
        NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY,
    )

    limiter = HostRateLimiter()
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    assert (
        limiter.default_interval_for_group("ncbi_api")
        == NCBI_DEFAULT_MIN_INTERVAL_NO_KEY
    )

    monkeypatch.setenv("NCBI_API_KEY", "test-key")
    assert (
        limiter.default_interval_for_group("ncbi_api")
        == NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY
    )


def test_host_rate_limiter_disabled_and_env_opt_out(monkeypatch):
    from pubmed_markdown.http_utils import HostRateLimiter

    disabled = HostRateLimiter(intervals={"ncbi_api": 1.0}, enabled=False)
    assert disabled.acquire("https://eutils.ncbi.nlm.nih.gov/test") == 0.0
    assert disabled.acquire("https://eutils.ncbi.nlm.nih.gov/test") == 0.0

    limiter = HostRateLimiter(intervals={"ncbi_api": 1.0})
    monkeypatch.setenv("PUBMED_MARKDOWN_DISABLE_RATE_LIMIT", "1")
    assert limiter.acquire("https://eutils.ncbi.nlm.nih.gov/test") == 0.0
    assert limiter.acquire("https://eutils.ncbi.nlm.nih.gov/test") == 0.0


def test_host_rate_limiter_thread_safe_dispatch_spacing():
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pubmed_markdown.http_utils import HostRateLimiter

    limiter = HostRateLimiter(intervals={"ncbi_api": 0.03})
    timestamps = []

    def worker():
        limiter.acquire("https://eutils.ncbi.nlm.nih.gov/test")
        timestamps.append(time.monotonic())

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker) for _ in range(4)]
        for f in futures:
            f.result()

    timestamps.sort()
    # 4 calls spaced by >= 0.03s should span at least ~0.075s total
    assert timestamps[-1] - timestamps[0] >= 0.07


def test_get_with_retries_uses_explicit_rate_limiter_and_api_key_interval():
    from pubmed_markdown.http_utils import (
        HostRateLimiter,
        NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY,
    )

    limiter = MagicMock(spec=HostRateLimiter)
    resp_200 = MagicMock(status_code=200, headers={}, text="ok")
    request_fn = MagicMock(return_value=resp_200)

    get_with_retries(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        request_fn=request_fn,
        params={"db": "pmc", "id": "123", "api_key": "secret"},
        rate_limiter=limiter,
    )

    limiter.acquire.assert_called_once_with(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        min_interval=NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY,
    )


# ---------------------------------------------------------------------------
# AsyncRateGate
# ---------------------------------------------------------------------------


def test_async_rate_gate_enforces_concurrency_and_interval():
    import asyncio
    import time
    from pubmed_markdown.http_utils import AsyncRateGate

    gate = AsyncRateGate(concurrency=2, min_interval=0.03)
    in_flight = 0
    max_in_flight = 0
    enter_times = []

    async def task():
        nonlocal in_flight, max_in_flight
        async with gate:
            enter_times.append(time.monotonic())
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.04)
            in_flight -= 1

    async def main():
        await asyncio.gather(*(task() for _ in range(4)))

    # Instantiated before loop exists; also verify reuse across a second loop
    asyncio.run(main())
    assert max_in_flight <= 2
    assert enter_times[-1] - enter_times[0] >= 0.07

    # Second event loop should transparently rebind primitives
    enter_times.clear()
    asyncio.run(main())
    assert len(enter_times) == 4


def test_async_rate_gate_for_ncbi_defaults(monkeypatch):
    from pubmed_markdown.http_utils import (
        AsyncRateGate,
        NCBI_DEFAULT_CONCURRENCY_NO_KEY,
        NCBI_DEFAULT_CONCURRENCY_WITH_KEY,
        NCBI_DEFAULT_MIN_INTERVAL_NO_KEY,
        NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY,
    )

    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    g_no_key = AsyncRateGate.for_ncbi()
    assert g_no_key.concurrency == NCBI_DEFAULT_CONCURRENCY_NO_KEY
    assert g_no_key.min_interval == NCBI_DEFAULT_MIN_INTERVAL_NO_KEY

    g_explicit_key = AsyncRateGate.for_ncbi(ncbi_key="abc123")
    assert g_explicit_key.concurrency == NCBI_DEFAULT_CONCURRENCY_WITH_KEY
    assert g_explicit_key.min_interval == NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY

    monkeypatch.setenv("NCBI_API_KEY", "env-key")
    g_env_key = AsyncRateGate.for_ncbi()
    assert g_env_key.concurrency == NCBI_DEFAULT_CONCURRENCY_WITH_KEY
    assert g_env_key.min_interval == NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY
