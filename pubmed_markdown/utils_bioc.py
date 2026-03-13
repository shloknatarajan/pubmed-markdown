"""
BioC API integration for fetching supplementary material text from PMC articles.

The BioC API provides pre-processed text from supplementary PDFs for articles
in the PMC Open Access subset. This is significantly easier than downloading
and parsing PDFs ourselves.

API Documentation: https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/FAIR-SMART/
"""

import json

import requests
from loguru import logger

BIOC_BASE_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/supplmat.cgi"


def fetch_bioc_supplement(pmcid: str) -> str | None:
    """
    Fetch supplementary material text from the BioC API.

    Args:
        pmcid: PubMed Central ID (e.g., "PMC6435416")

    Returns:
        Extracted text from all supplementary materials, or None if not available.
    """
    url = f"{BIOC_BASE_URL}/BioC_JSON/{pmcid}/All"

    try:
        response = requests.get(url, timeout=30)

        if response.status_code != 200:
            logger.debug(
                f"No supplements found for {pmcid} (HTTP {response.status_code})"
            )
            return None

        content = response.text
        if not content or len(content) < 50:
            logger.debug(f"No supplements found for {pmcid} (empty response)")
            return None

        # Parse BioC JSON and extract text
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # The BioC API returns non-JSON (HTML) when no supplements exist
            logger.debug(f"No supplements found for {pmcid}")
            return None

        all_text = _extract_text_from_bioc(data)

        if all_text:
            return all_text
        else:
            logger.debug(f"No supplements found for {pmcid} (no text in response)")
            return None

    except requests.RequestException as e:
        logger.warning(f"BioC API request failed for {pmcid}: {e}")
        return None


def _extract_text_from_bioc_structured(data: list | dict) -> list[dict[str, str]]:
    """
    Extract text passages from BioC JSON response, organized by document.

    Returns a list of dicts with 'filename' and 'text' keys, one per document.

    BioC JSON structure:
    [
        {
            "source": "BioC",
            "documents": [
                {
                    "id": "filename.pdf",
                    "passages": [
                        {"offset": 0, "text": "...", "annotations": []}
                    ]
                }
            ]
        }
    ]
    """
    documents = []

    # Handle both list and dict responses
    collections = data if isinstance(data, list) else [data]

    for collection in collections:
        if not isinstance(collection, dict):
            continue

        for doc in collection.get("documents", []):
            if not isinstance(doc, dict):
                continue

            filename = doc.get("id", "unknown")
            passages = []

            for passage in doc.get("passages", []):
                if not isinstance(passage, dict):
                    continue

                text = passage.get("text", "")
                if text and isinstance(text, str):
                    passages.append(text)

            if passages:
                documents.append({"filename": filename, "text": "\n\n".join(passages)})

    return documents


def _extract_text_from_bioc(data: list | dict) -> str:
    """
    Extract all text passages from BioC JSON response as a flat string.

    Wrapper around _extract_text_from_bioc_structured for backward compatibility.
    """
    docs = _extract_text_from_bioc_structured(data)
    return "\n\n".join(doc["text"] for doc in docs)


def format_supplement_as_markdown(pmcid: str) -> str | None:
    """
    Fetch supplementary material for a PMCID and format it as a markdown section.

    Args:
        pmcid: PubMed Central ID (e.g., "PMC6435416")

    Returns:
        A formatted markdown string with ## Supplementary Materials header,
        or None if no supplements are available.
    """
    url = f"{BIOC_BASE_URL}/BioC_JSON/{pmcid}/All"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None
        content = response.text
        if not content or len(content) < 50:
            return None
        raw_data = json.loads(content)
    except (requests.RequestException, json.JSONDecodeError):
        return None

    docs = _extract_text_from_bioc_structured(raw_data)
    if not docs:
        return None

    lines = ["## Supplementary Materials"]
    for doc in docs:
        lines.append(f"\n### {doc['filename']}\n")
        lines.append(doc["text"])

    return "\n".join(lines)


if __name__ == "__main__":
    # Test with a known article
    test_pmcid = "PMC6435416"
    print(f"Testing BioC fetch for {test_pmcid}...")

    text = fetch_bioc_supplement(test_pmcid)

    if text:
        print(f"Got {len(text)} characters of supplement text")
        print(f"\nFirst 500 chars:\n{text[:500]}")

        # Check for expected content
        if "*17" in text and "*41" in text:
            print("\nFound expected CYP2D6 star alleles in supplement!")
    else:
        print("No supplement available")
