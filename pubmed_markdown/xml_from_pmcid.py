"""
PMCID --> Full Article Text (JATS XML)

Fetches full-text JATS XML via:
1. NCBI E-utilities efetch (official programmatic API, no AWS WAF)
2. Europe PMC fullTextXML (best-effort fallback when NCBI fails or omits <body>)
"""

import os
import re
from typing import List, Literal, Optional, Tuple

import requests
from loguru import logger

from .http_utils import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, get_with_retries
from .models import TierError

NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EUROPE_PMC_FULLTEXT_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
)
EUROPE_PMC_DEFAULT_TIMEOUT: float = 15.0

_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_XML_RESTRICTED_MARKER = "does not allow downloading of the full text in xml form"


def normalize_pmcid(pmcid: str) -> str:
    """Normalize a PMCID string to uppercase 'PMC<digits>' form."""
    cleaned = pmcid.strip()
    if cleaned.upper().startswith("PMC"):
        return f"PMC{cleaned[3:]}"
    return f"PMC{cleaned}"


def is_xml_restricted(xml_content: str) -> bool:
    """Return True if NCBI returned a publisher XML download restriction notice."""
    if not isinstance(xml_content, str):
        return False
    return _XML_RESTRICTED_MARKER in xml_content.lower()


def jats_has_full_text(xml_content: str) -> bool:
    """
    Return True if the JATS XML contains an <article> with a non-empty <body>.

    Publishers that opt out of PMC XML redistribution return metadata and
    abstract only (no <body> element).
    """
    if not isinstance(xml_content, str) or not xml_content.strip():
        return False
    if "<article" not in xml_content.lower():
        return False
    match = _BODY_RE.search(xml_content)
    if not match:
        return False
    body_text = _TAG_RE.sub(" ", match.group(1)).strip()
    return len(body_text) > 0


def fetch_xml_from_ncbi_efetch(
    pmcid: str,
    email: Optional[str] = None,
    ncbi_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    require_full_text: bool = True,
) -> Tuple[Optional[str], Optional[TierError]]:
    """
    Fetch JATS XML for a PMCID from NCBI E-utilities efetch (db=pmc), returning
    `(xml_text, None)` on success or `(None, TierError)` on failure.
    """
    if not isinstance(pmcid, str) or not pmcid.strip():
        logger.error("pmcid must be a non-empty string")
        return None, TierError(
            tier="ncbi_xml",
            code="invalid_input",
            message="pmcid must be a non-empty string",
        )

    normalized = normalize_pmcid(pmcid)
    pmcid_num = normalized[3:]

    contact_email = email or os.getenv("NCBI_EMAIL")
    key = ncbi_key or os.getenv("NCBI_API_KEY")

    params = {
        "db": "pmc",
        "id": pmcid_num,
        "retmode": "xml",
        "tool": "pubmed-markdown",
    }
    if contact_email:
        params["email"] = contact_email
    if key:
        params["api_key"] = key

    response = None
    try:
        response = get_with_retries(
            NCBI_EFETCH_URL,
            request_fn=requests.get,
            params=params,
            timeout=timeout,
            max_retries=max_retries,
            context=f"NCBI efetch XML {normalized}",
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status = response.status_code if response is not None else None
        logger.error(f"NCBI efetch HTTP error for {normalized}: {e}")
        if response is not None and response.text:
            logger.error(f"Server response: {response.text[:500]}")
        return None, TierError(
            tier="ncbi_xml",
            code="not_found" if status == 404 else "http_error",
            message=str(e),
            status_code=status,
        )
    except requests.exceptions.Timeout as e:
        logger.error(f"NCBI efetch request timed out for {normalized}: {e}")
        return None, TierError(tier="ncbi_xml", code="timeout", message=str(e))
    except requests.exceptions.ConnectionError as e:
        logger.error(f"NCBI efetch connection failed for {normalized}: {e}")
        return None, TierError(tier="ncbi_xml", code="connection_error", message=str(e))
    except requests.exceptions.RequestException as e:
        logger.error(f"NCBI efetch request failed for {normalized}: {e}")
        return None, TierError(tier="ncbi_xml", code="request_error", message=str(e))

    xml_text = response.text
    if not xml_text or "<article" not in xml_text.lower():
        logger.warning(f"NCBI efetch returned no <article> for {normalized}")
        return None, TierError(
            tier="ncbi_xml",
            code="empty_output",
            message=f"NCBI efetch returned no <article> for {normalized}",
        )

    if require_full_text and not jats_has_full_text(xml_text):
        if is_xml_restricted(xml_text):
            logger.info(
                f"Publisher restricts XML download for {normalized} via NCBI efetch"
            )
            return None, TierError(
                tier="ncbi_xml",
                code="xml_restricted",
                message=f"Publisher restricts XML download for {normalized} via NCBI efetch",
            )
        logger.info(f"NCBI efetch XML for {normalized} has no full-text <body> element")
        return None, TierError(
            tier="ncbi_xml",
            code="no_full_text_body",
            message=f"NCBI efetch XML for {normalized} has no full-text <body> element",
        )

    return xml_text, None


def get_xml_from_ncbi_efetch(
    pmcid: str,
    email: Optional[str] = None,
    ncbi_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    require_full_text: bool = True,
) -> Optional[str]:
    """
    Fetch JATS XML for a PMCID from NCBI E-utilities efetch (db=pmc).

    Args:
        pmcid: PMCID to fetch (e.g. "PMC10275785").
        email: Email for NCBI API identification. Falls back to NCBI_EMAIL env var.
        ncbi_key: NCBI API key (10 req/s vs 3 req/s). Falls back to NCBI_API_KEY env var.
        timeout: HTTP request timeout in seconds (default: 30.0).
        max_retries: Number of retries for transient errors (default: 2).
        require_full_text: If True, return None when <body> is absent (e.g. publisher
            opt-out), allowing callers to fall back to Europe PMC or PMC HTML.

    Returns:
        JATS XML string if successful, or None on error / missing full text.
    """
    xml_text, _ = fetch_xml_from_ncbi_efetch(
        pmcid,
        email=email,
        ncbi_key=ncbi_key,
        timeout=timeout,
        max_retries=max_retries,
        require_full_text=require_full_text,
    )
    return xml_text


def fetch_xml_from_europe_pmc(
    pmcid: str,
    timeout: float = EUROPE_PMC_DEFAULT_TIMEOUT,
    max_retries: int = 0,
    require_full_text: bool = True,
) -> Tuple[Optional[str], Optional[TierError]]:
    """
    Fetch JATS XML for a PMCID from Europe PMC REST API, returning
    `(xml_text, None)` on success or `(None, TierError)` on failure.
    """
    if not isinstance(pmcid, str) or not pmcid.strip():
        logger.error("pmcid must be a non-empty string")
        return None, TierError(
            tier="europe_pmc_xml",
            code="invalid_input",
            message="pmcid must be a non-empty string",
        )

    normalized = normalize_pmcid(pmcid)
    url = EUROPE_PMC_FULLTEXT_URL.format(pmcid=normalized)

    response = None
    try:
        response = get_with_retries(
            url,
            request_fn=requests.get,
            timeout=timeout,
            max_retries=max_retries,
            context=f"Europe PMC XML {normalized}",
        )
        if response.status_code == 404:
            logger.debug(f"Europe PMC fullTextXML not available for {normalized} (404)")
            return None, TierError(
                tier="europe_pmc_xml",
                code="not_found",
                message=f"Europe PMC fullTextXML not available for {normalized} (404)",
                status_code=404,
            )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status = response.status_code if response is not None else None
        logger.warning(f"Europe PMC XML HTTP error for {normalized}: {e}")
        return None, TierError(
            tier="europe_pmc_xml",
            code="not_found" if status == 404 else "http_error",
            message=str(e),
            status_code=status,
        )
    except requests.exceptions.Timeout as e:
        logger.warning(f"Europe PMC XML request timed out for {normalized}: {e}")
        return None, TierError(tier="europe_pmc_xml", code="timeout", message=str(e))
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Europe PMC XML connection failed for {normalized}: {e}")
        return None, TierError(
            tier="europe_pmc_xml", code="connection_error", message=str(e)
        )
    except requests.exceptions.RequestException as e:
        logger.warning(f"Europe PMC XML request failed for {normalized}: {e}")
        return None, TierError(
            tier="europe_pmc_xml", code="request_error", message=str(e)
        )

    xml_text = response.text
    if not xml_text or "<article" not in xml_text.lower():
        logger.debug(f"Europe PMC returned no <article> for {normalized}")
        return None, TierError(
            tier="europe_pmc_xml",
            code="empty_output",
            message=f"Europe PMC returned no <article> for {normalized}",
        )

    if require_full_text and not jats_has_full_text(xml_text):
        logger.info(f"Europe PMC XML for {normalized} has no full-text <body> element")
        return None, TierError(
            tier="europe_pmc_xml",
            code="no_full_text_body",
            message=f"Europe PMC XML for {normalized} has no full-text <body> element",
        )

    return xml_text, None


def get_xml_from_europe_pmc(
    pmcid: str,
    timeout: float = EUROPE_PMC_DEFAULT_TIMEOUT,
    max_retries: int = 0,
    require_full_text: bool = True,
) -> Optional[str]:
    """
    Fetch JATS XML for a PMCID from Europe PMC REST API (best-effort fallback).

    Args:
        pmcid: PMCID to fetch (e.g. "PMC10275785").
        timeout: HTTP request timeout in seconds (default: 15.0).
        max_retries: Number of retries for transient errors (default: 0 for fast fallback).
        require_full_text: If True, return None when <body> is absent.

    Returns:
        JATS XML string if successful, or None on error / unavailable.
    """
    xml_text, _ = fetch_xml_from_europe_pmc(
        pmcid,
        timeout=timeout,
        max_retries=max_retries,
        require_full_text=require_full_text,
    )
    return xml_text


def fetch_xml_from_pmcid(
    pmcid: str,
    email: Optional[str] = None,
    ncbi_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    use_europe_pmc_fallback: bool = True,
    europe_pmc_timeout: float = EUROPE_PMC_DEFAULT_TIMEOUT,
    require_full_text: bool = True,
) -> Tuple[
    Optional[str], Optional[Literal["ncbi_xml", "europe_pmc_xml"]], List[TierError]
]:
    """
    Fetch full-text JATS XML for a PMCID with structured tier attribution and error diagnostics.

    Returns:
        Tuple of `(xml_text, source_tier, errors)`.
    """
    errors: List[TierError] = []
    xml, ncbi_err = fetch_xml_from_ncbi_efetch(
        pmcid,
        email=email,
        ncbi_key=ncbi_key,
        timeout=timeout,
        max_retries=max_retries,
        require_full_text=require_full_text,
    )
    if xml is not None:
        return xml, "ncbi_xml", errors
    if ncbi_err is not None:
        errors.append(ncbi_err)

    if use_europe_pmc_fallback:
        xml, epmc_err = fetch_xml_from_europe_pmc(
            pmcid,
            timeout=europe_pmc_timeout,
            require_full_text=require_full_text,
        )
        if xml is not None:
            return xml, "europe_pmc_xml", errors
        if epmc_err is not None:
            errors.append(epmc_err)

    return None, None, errors


def get_xml_from_pmcid(
    pmcid: str,
    email: Optional[str] = None,
    ncbi_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    use_europe_pmc_fallback: bool = True,
    europe_pmc_timeout: float = EUROPE_PMC_DEFAULT_TIMEOUT,
    require_full_text: bool = True,
) -> Optional[str]:
    """
    Fetch full-text JATS XML for a PMCID, trying NCBI E-utilities first and
    optionally falling back to Europe PMC.

    Args:
        pmcid: PMCID to fetch (e.g. "PMC10275785").
        email: Email for NCBI API identification. Falls back to NCBI_EMAIL env var.
        ncbi_key: NCBI API key. Falls back to NCBI_API_KEY env var.
        timeout: HTTP timeout in seconds for NCBI efetch (default: 30.0).
        max_retries: Retry count for NCBI efetch (default: 2).
        use_europe_pmc_fallback: Whether to try Europe PMC if NCBI fails or omits <body>.
        europe_pmc_timeout: HTTP timeout in seconds for Europe PMC (default: 15.0).
        require_full_text: Require a non-empty <body> element in the JATS XML.

    Returns:
        JATS XML string if successful, or None otherwise.
    """
    xml = get_xml_from_ncbi_efetch(
        pmcid,
        email=email,
        ncbi_key=ncbi_key,
        timeout=timeout,
        max_retries=max_retries,
        require_full_text=require_full_text,
    )
    if xml is not None:
        return xml

    if use_europe_pmc_fallback:
        return get_xml_from_europe_pmc(
            pmcid,
            timeout=europe_pmc_timeout,
            require_full_text=require_full_text,
        )

    return None
