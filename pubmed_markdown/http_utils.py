"""
Shared HTTP utilities: timeouts, retry with exponential backoff + jitter,
Retry-After parsing, AWS WAF / CAPTCHA HTML detection, host-aware rate
limiting, and async concurrency/dispatch gating.
"""

import asyncio
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Optional, Union
from urllib.parse import urlparse

import requests
from loguru import logger

DEFAULT_TIMEOUT: float = 30.0
DEFAULT_MAX_RETRIES: int = 2
DEFAULT_BACKOFF_FACTOR: float = 1.0
MAX_RETRY_AFTER: float = 60.0
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# NCBI API defaults (~3 req/s without key, ~8 req/s with key to leave headroom below 10 req/s)
NCBI_DEFAULT_CONCURRENCY_NO_KEY: int = 3
NCBI_DEFAULT_CONCURRENCY_WITH_KEY: int = 8
NCBI_DEFAULT_MIN_INTERVAL_NO_KEY: float = 0.35
NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY: float = 0.12
PMC_HTML_DEFAULT_MIN_INTERVAL: float = 0.5
EUROPE_PMC_DEFAULT_MIN_INTERVAL: float = 0.1

_ORIG_REQUESTS_GET = requests.get
_thread_local = threading.local()


def get_http_session() -> requests.Session:
    """Return a thread-local requests.Session for HTTP keep-alive connection pooling."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def _host_group_for_url(url: str) -> str:
    """Map an upstream URL to a rate-limit host group."""
    hostname = (urlparse(url).hostname or "").lower()
    if hostname in ("eutils.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"):
        return "ncbi_api"
    if hostname == "pmc.ncbi.nlm.nih.gov":
        return "pmc_html"
    if hostname == "www.ebi.ac.uk":
        return "europe_pmc"
    return hostname or "default"


class HostRateLimiter:
    """
    Thread-safe per-host-group minimum dispatch interval rate limiter.

    Reserves the next allowed dispatch timestamp under a per-group lock and
    sleeps outside the lock so concurrent threads strictly respect upstream
    rate limits without blocking unrelated hosts (e.g. Europe PMC vs NCBI).
    """

    def __init__(
        self,
        intervals: Optional[Dict[str, float]] = None,
        enabled: bool = True,
    ):
        self._custom_intervals: Dict[str, float] = dict(intervals or {})
        self.enabled = enabled
        self._meta_lock = threading.Lock()
        self._group_locks: Dict[str, threading.Lock] = {}
        self._next_allowed: Dict[str, float] = {}

    def default_interval_for_group(self, group: str) -> float:
        """Return the configured or default minimum dispatch interval for a host group."""
        if group in self._custom_intervals:
            return self._custom_intervals[group]
        if group == "ncbi_api":
            has_key = bool(os.getenv("NCBI_API_KEY"))
            return (
                NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY
                if has_key
                else NCBI_DEFAULT_MIN_INTERVAL_NO_KEY
            )
        if group == "pmc_html":
            return PMC_HTML_DEFAULT_MIN_INTERVAL
        if group == "europe_pmc":
            return EUROPE_PMC_DEFAULT_MIN_INTERVAL
        return 0.0

    def _get_group_lock(self, group: str) -> threading.Lock:
        with self._meta_lock:
            lock = self._group_locks.get(group)
            if lock is None:
                lock = threading.Lock()
                self._group_locks[group] = lock
            return lock

    def acquire(
        self,
        url: str,
        min_interval: Optional[float] = None,
    ) -> float:
        """
        Wait until a request to `url`'s host group is permitted.

        Args:
            url: Target URL.
            min_interval: Optional per-call interval override in seconds.

        Returns:
            Seconds slept (0.0 if dispatched immediately or disabled).
        """
        if not self.enabled:
            return 0.0
        if os.getenv("PUBMED_MARKDOWN_DISABLE_RATE_LIMIT", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            return 0.0

        group = _host_group_for_url(url)
        interval = (
            min_interval
            if min_interval is not None
            else self.default_interval_for_group(group)
        )
        if interval <= 0:
            return 0.0

        lock = self._get_group_lock(group)
        with lock:
            now = time.monotonic()
            scheduled = max(now, self._next_allowed.get(group, 0.0))
            self._next_allowed[group] = scheduled + interval
            wait = scheduled - now

        if wait > 0:
            time.sleep(wait)
        return wait

    def reset(self) -> None:
        """Clear all scheduled dispatch timestamps (useful in tests)."""
        with self._meta_lock:
            self._next_allowed.clear()


_default_rate_limiter = HostRateLimiter()


def get_host_rate_limiter() -> HostRateLimiter:
    """Return the process-wide default thread-safe HostRateLimiter."""
    return _default_rate_limiter


class AsyncRateGate:
    """
    Async concurrency limiter + minimum dispatch interval gate.

    Lazily binds its `asyncio.Semaphore` and `asyncio.Lock` to the currently
    running event loop, so instances can safely be created at module import time
    or reused across separate event loops in test suites.
    """

    def __init__(self, concurrency: int = 3, min_interval: float = 0.35):
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if min_interval < 0:
            raise ValueError("min_interval must be >= 0")
        self.concurrency = concurrency
        self.min_interval = min_interval
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._lock: Optional[asyncio.Lock] = None
        self._last_dispatch: float = 0.0

    @classmethod
    def for_ncbi(
        cls,
        ncbi_key: Optional[str] = None,
        concurrency: Optional[int] = None,
        min_interval: Optional[float] = None,
    ) -> "AsyncRateGate":
        """Create an AsyncRateGate sized for NCBI quotas based on NCBI_API_KEY availability."""
        has_key = bool(ncbi_key or os.getenv("NCBI_API_KEY"))
        eff_concurrency = (
            concurrency
            if concurrency is not None
            else (
                NCBI_DEFAULT_CONCURRENCY_WITH_KEY
                if has_key
                else NCBI_DEFAULT_CONCURRENCY_NO_KEY
            )
        )
        eff_interval = (
            min_interval
            if min_interval is not None
            else (
                NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY
                if has_key
                else NCBI_DEFAULT_MIN_INTERVAL_NO_KEY
            )
        )
        return cls(concurrency=eff_concurrency, min_interval=eff_interval)

    def _ensure_primitives(self) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._sem is None or self._lock is None:
            self._loop = loop
            self._sem = asyncio.Semaphore(self.concurrency)
            self._lock = asyncio.Lock()
            self._last_dispatch = 0.0
        return self._sem, self._lock

    async def __aenter__(self) -> "AsyncRateGate":
        sem, lock = self._ensure_primitives()
        await sem.acquire()
        try:
            async with lock:
                if self.min_interval > 0:
                    now = time.monotonic()
                    wait = self.min_interval - (now - self._last_dispatch)
                    if wait > 0:
                        await asyncio.sleep(wait)
                self._last_dispatch = time.monotonic()
        except BaseException:
            sem.release()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._sem is not None:
            self._sem.release()


_PMC_ARTICLE_RE = re.compile(
    r"(?:name=[\"'](?:citation_title|ncbi_type)[\"']"
    r"|class=[\"'][^\"']*\b(?:main-article-body|abstract|scanned-pages)\b)",
    re.IGNORECASE,
)

_WAF_TITLE_RE = re.compile(
    r"<title[^>]*>[^<]*(?:"
    r"checking your browser|recaptcha|access denied|403 forbidden|"
    r"just a moment|attention required|human verification|"
    r"bot verification|request blocked"
    r")[^<]*</title>",
    re.IGNORECASE,
)

_WAF_BODY_MARKERS = (
    "checking your browser",
    "awswaf",
    "aws-waf",
    "aws_waf",
    "token.awswaf.com",
    "challenge.awswaf.com",
    "g-recaptcha",
    "recaptcha/api.js",
    "google.com/recaptcha",
    "verify you are human",
    "please verify that you are not a robot",
    "cf-challenge",
    "challenge-platform",
    "<h1>403 forbidden</h1>",
)


class WAFChallengeError(requests.exceptions.RequestException):
    """Raised when an HTTP 200 response is a WAF/CAPTCHA challenge or invalid page."""


def is_waf_or_captcha_html(html: str) -> bool:
    """
    Detect whether an HTML response is a WAF/CAPTCHA challenge or block page
    rather than a PMC article.

    Checks for authentic PMC article structural markers first to avoid false
    positives on articles that mention terms like "reCAPTCHA" in their text.
    """
    if not isinstance(html, str) or not html:
        return False

    if _PMC_ARTICLE_RE.search(html):
        return False

    if _WAF_TITLE_RE.search(html):
        return True

    lowered = html.lower()
    return any(marker in lowered for marker in _WAF_BODY_MARKERS)


def parse_retry_after(
    value: Optional[str], max_wait: float = MAX_RETRY_AFTER
) -> Optional[float]:
    """Parse an HTTP Retry-After header (seconds or HTTP-date) into delay seconds."""
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped:
        return None

    try:
        seconds = float(stripped)
        return max(0.0, min(seconds, max_wait))
    except ValueError:
        pass

    try:
        retry_dt = parsedate_to_datetime(stripped)
        if retry_dt.tzinfo is None:
            retry_dt = retry_dt.replace(tzinfo=timezone.utc)
        delay = (retry_dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(delay, max_wait))
    except (TypeError, ValueError):
        return None


def compute_backoff(
    attempt: int,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    retry_after: Optional[str] = None,
    max_wait: float = MAX_RETRY_AFTER,
) -> float:
    """Compute retry delay honoring Retry-After if present, else exponential backoff + jitter."""
    parsed = parse_retry_after(retry_after, max_wait=max_wait)
    if parsed is not None:
        return parsed

    base_delay = backoff_factor * (2**attempt)
    jitter = random.uniform(0.0, 0.5 * backoff_factor)
    return min(base_delay + jitter, max_wait)


def get_with_retries(
    url: str,
    *,
    request_fn: Callable[..., requests.Response] = requests.get,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    retry_statuses: frozenset[int] = RETRYABLE_STATUS_CODES,
    validate_response: Optional[Callable[[requests.Response], Optional[str]]] = None,
    context: str = "",
    rate_limiter: Optional[Union[HostRateLimiter, bool]] = None,
    rate_limit_interval: Optional[float] = None,
) -> requests.Response:
    """
    Perform an HTTP GET with explicit timeout, host-aware rate limiting, and
    retries on transient failures.

    Retries on:
      - ConnectionError / Timeout
      - HTTP status codes in `retry_statuses` (default: 429, 500, 502, 503, 504)
      - Optional `validate_response(response)` returning a non-None failure reason
        (raises WAFChallengeError if all attempts fail validation)
    """
    kwargs: Dict[str, Any] = {"timeout": timeout}
    if headers is not None:
        kwargs["headers"] = headers
    if params is not None:
        kwargs["params"] = params

    label = f" ({context})" if context else ""
    attempts = max(1, max_retries + 1)
    is_real_request = request_fn is _ORIG_REQUESTS_GET
    # Use thread-local pooled Session for real unpatched requests.get calls,
    # while honoring patched mocks (e.g. unittest.mock.patch("...requests.get")).
    effective_request_fn = get_http_session().get if is_real_request else request_fn

    # Apply host-aware rate limiting automatically on real HTTP calls, or whenever
    # a HostRateLimiter instance is explicitly passed. Pass rate_limiter=False to opt out.
    active_limiter: Optional[HostRateLimiter]
    if isinstance(rate_limiter, HostRateLimiter):
        active_limiter = rate_limiter
    elif rate_limiter is False:
        active_limiter = None
    elif rate_limiter is True or is_real_request:
        active_limiter = _default_rate_limiter
    else:
        active_limiter = None

    effective_interval = rate_limit_interval
    if (
        effective_interval is None
        and params is not None
        and params.get("api_key")
        and _host_group_for_url(url) == "ncbi_api"
    ):
        effective_interval = NCBI_DEFAULT_MIN_INTERVAL_WITH_KEY

    for attempt in range(attempts):
        if active_limiter is not None:
            active_limiter.acquire(url, min_interval=effective_interval)
        try:
            response = effective_request_fn(url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < attempts - 1:
                delay = compute_backoff(attempt, backoff_factor=backoff_factor)
                logger.warning(
                    f"Transient network error{label}: {e}. "
                    f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{attempts})..."
                )
                time.sleep(delay)
                continue
            raise

        if response.status_code in retry_statuses and attempt < attempts - 1:
            raw_headers = getattr(response, "headers", None)
            retry_after = (
                raw_headers.get("Retry-After") if hasattr(raw_headers, "get") else None
            )
            delay = compute_backoff(
                attempt,
                backoff_factor=backoff_factor,
                retry_after=retry_after if isinstance(retry_after, str) else None,
            )
            logger.warning(
                f"HTTP {response.status_code}{label}. "
                f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{attempts})..."
            )
            time.sleep(delay)
            continue

        if response.status_code == 200 and validate_response is not None:
            invalid_reason = validate_response(response)
            if invalid_reason is not None:
                if attempt < attempts - 1:
                    delay = compute_backoff(attempt, backoff_factor=backoff_factor)
                    logger.warning(
                        f"Invalid response{label}: {invalid_reason}. "
                        f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{attempts})..."
                    )
                    time.sleep(delay)
                    continue
                raise WAFChallengeError(invalid_reason)

        return response

    raise RuntimeError(f"Unexpected retry loop exit{label}")
