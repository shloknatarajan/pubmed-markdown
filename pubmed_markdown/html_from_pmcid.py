"""
PMCID --> Full Article Text (HTML)
This uses a standard get request with a user agent and accept header to fetch the article text.
"""

import os
from importlib.metadata import version
from typing import Optional

import requests
from loguru import logger

from .http_utils import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    WAFChallengeError,
    get_with_retries,
    is_waf_or_captcha_html,
)


def _validate_pmc_html(response: requests.Response) -> Optional[str]:
    """Return a failure reason if the HTTP 200 HTML response is empty or a WAF/CAPTCHA page."""
    text = response.text
    if not isinstance(text, str) or not text.strip():
        return "Empty HTML response from PMC"
    if is_waf_or_captcha_html(text):
        return "AWS WAF / CAPTCHA challenge page returned instead of PMC article"
    return None


def get_html_from_pmcid(
    pmcid: str,
    email: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Optional[str]:
    """
    Given a PMCID, fetch the full article text from the NCBI website.
    Returns the HTML text of the article in string format from the url
    https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=classic

    Args:
        pmcid (str): The PMCID to fetch
        email (str, optional): Email for NCBI identification. Falls back to NCBI_EMAIL env var.
        timeout (float): HTTP request timeout in seconds (default: 30.0)
        max_retries (int): Number of retry attempts for transient/WAF errors (default: 2)

    Returns:
        Optional[str]: The article html text if successful, None if there was an error
    """
    if not isinstance(pmcid, str):
        logger.error("pmcid must be a string")
        return None

    contact_email = email or os.getenv("NCBI_EMAIL", "")
    try:
        pkg_version = version("pubmed-markdown")
    except Exception:
        pkg_version = "0.0.0"

    user_agent = f"pubmed-markdown/{pkg_version}"
    if contact_email:
        user_agent += f" (mailto:{contact_email})"

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=classic"
    response = None
    try:
        response = get_with_retries(
            url,
            request_fn=requests.get,
            headers=headers,
            timeout=timeout,
            max_retries=max_retries,
            validate_response=_validate_pmc_html,
            context=f"PMCID {pmcid}",
        )
        response.raise_for_status()
        return response.text
    except WAFChallengeError as e:
        logger.error(f"WAF/CAPTCHA block for PMCID {pmcid}: {e}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred for PMCID {pmcid}: {str(e)}")
        if response is not None and response.text:
            logger.error(f"Server response: {response.text[:500]}")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error occurred for PMCID {pmcid}: {str(e)}")
        return None
    except requests.exceptions.Timeout as e:
        logger.error(f"Request timed out for PMCID {pmcid}: {str(e)}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while fetching PMCID {pmcid}: {str(e)}")
        return None
