"""
Shared HTTP utilities: timeouts, retry with exponential backoff + jitter,
Retry-After parsing, and AWS WAF / CAPTCHA HTML detection.
"""

import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Optional

import requests
from loguru import logger

DEFAULT_TIMEOUT: float = 30.0
DEFAULT_MAX_RETRIES: int = 2
DEFAULT_BACKOFF_FACTOR: float = 1.0
MAX_RETRY_AFTER: float = 60.0
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_ORIG_REQUESTS_GET = requests.get
_thread_local = threading.local()


def get_http_session() -> requests.Session:
    """Return a thread-local requests.Session for HTTP keep-alive connection pooling."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


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
) -> requests.Response:
    """
    Perform an HTTP GET with explicit timeout and retries on transient failures.

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
    # Use thread-local pooled Session for real unpatched requests.get calls,
    # while honoring patched mocks (e.g. unittest.mock.patch("...requests.get")).
    effective_request_fn = (
        get_http_session().get if request_fn is _ORIG_REQUESTS_GET else request_fn
    )

    for attempt in range(attempts):
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
