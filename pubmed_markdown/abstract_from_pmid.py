"""
PMID --> Abstract (via NCBI E-Fetch API)

Fetches the abstract and basic metadata for articles that are not available
in PubMed Central (no PMCID). Returns a simple markdown-formatted string.
"""

import os
import requests
import xml.etree.ElementTree as ET
from typing import Optional
from loguru import logger

from .http_utils import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, get_with_retries


def get_abstract_markdown_from_pmid(
    pmid: str,
    email: Optional[str] = None,
    ncbi_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Optional[str]:
    """
    Fetch the abstract and metadata for a PMID from PubMed and return as markdown.

    Args:
        pmid (str): The PubMed ID to fetch
        email (str, optional): Email for NCBI API identification. Falls back to NCBI_EMAIL env var.
        ncbi_key (str, optional): NCBI API key (increases rate limit from 3 to 10 req/s).
            Falls back to NCBI_API_KEY env var.
        timeout (float): HTTP request timeout in seconds (default: 30.0)
        max_retries (int): Number of retry attempts for transient errors (default: 2)

    Returns:
        Optional[str]: Markdown-formatted abstract with title/authors, or None on failure
    """
    if not email:
        email = os.getenv("NCBI_EMAIL")
    if not email:
        logger.warning(
            "No email provided. Please set the NCBI_EMAIL environment variable "
            "or pass email explicitly. NCBI may block requests without identification."
        )

    if not ncbi_key:
        ncbi_key = os.getenv("NCBI_API_KEY")

    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": pmid,
        "rettype": "xml",
        "retmode": "xml",
        "tool": "pubmed_downloader",
        "email": email,
    }
    if ncbi_key:
        params["api_key"] = ncbi_key

    try:
        response = get_with_retries(
            url,
            request_fn=requests.get,
            params=params,
            timeout=timeout,
            max_retries=max_retries,
            context=f"abstract PMID {pmid}",
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch abstract for PMID {pmid}: {e}")
        return None

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as e:
        logger.error(f"Failed to parse XML for PMID {pmid}: {e}")
        return None

    article = root.find(".//PubmedArticle")
    if article is None:
        logger.error(f"No article found in response for PMID {pmid}")
        return None

    # Extract title
    title_el = article.find(".//ArticleTitle")
    title = _get_element_text(title_el) if title_el is not None else "Unknown Title"

    # Extract authors
    authors = []
    for author in article.findall(".//Author"):
        last = author.findtext("LastName", "")
        fore = author.findtext("ForeName", "")
        if last:
            authors.append(f"{fore} {last}".strip())

    # Extract abstract
    abstract_parts = []
    for abstract_text in article.findall(".//AbstractText"):
        label = abstract_text.get("Label")
        text = _get_element_text(abstract_text)
        if text:
            if label:
                abstract_parts.append(f"**{label}:** {text}")
            else:
                abstract_parts.append(text)

    abstract = (
        "\n\n".join(abstract_parts) if abstract_parts else "No abstract available."
    )

    # Extract journal info
    journal = article.findtext(".//Journal/Title", "")
    year = article.findtext(".//PubDate/Year", "")
    doi_el = article.find(".//ArticleId[@IdType='doi']")
    doi = doi_el.text if doi_el is not None and doi_el.text else None

    # Build markdown
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    if authors:
        lines.append(", ".join(authors))
        lines.append("")
    if journal or year:
        lines.append(f"*{journal}* ({year})".strip())
        lines.append("")
    lines.append(f"PMID: {pmid}")
    if doi:
        lines.append(f"DOI: {doi}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "**Note: This article is not available on PubMed Central (Open Access). Only the abstract is included below.**"
    )
    lines.append("")
    lines.append("## Abstract")
    lines.append("")
    lines.append(abstract)
    lines.append("")

    return "\n".join(lines)


def _get_element_text(element) -> str:
    """Extract all text from an element, including text within child tags (e.g. <i>, <b>)."""
    return "".join(element.itertext()).strip()
