"""
PMCID --> Full Article Text (JATS XML via NCBI E-utilities)

Uses the official NCBI E-utilities efetch API for reliable programmatic access.
The old approach of scraping the PMC web page no longer works because
pmc.ncbi.nlm.nih.gov blocks automated requests with 403 Forbidden.
"""

import argparse
import os
import requests
from loguru import logger
from typing import Optional


EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def get_html_from_pmcid(pmcid: str, email: str = None) -> Optional[str]:
    """
    Given a PMCID, fetch the full article JATS XML from NCBI E-utilities.

    Uses the efetch API which is the officially supported method for
    programmatic access to PMC articles. Set NCBI_EMAIL and optionally
    NCBI_API_KEY environment variables for identification and higher rate limits.

    Args:
        pmcid (str): The PMCID to fetch (e.g. "PMC10275785")
        email (str): Optional email for NCBI identification. Falls back to NCBI_EMAIL env var.

    Returns:
        Optional[str]: The article JATS XML text if successful, None if there was an error
    """
    if not isinstance(pmcid, str):
        logger.error("pmcid must be a string")
        return None

    # Strip "PMC" prefix - efetch expects just the numeric ID
    pmcid_num = pmcid.replace("PMC", "")

    email = email or os.environ.get("NCBI_EMAIL", "")
    api_key = os.environ.get("NCBI_API_KEY", "")

    params = {
        "db": "pmc",
        "id": pmcid_num,
        "rettype": "full",
        "retmode": "xml",
    }
    if email:
        params["email"] = email
        params["tool"] = "pubmed-markdown"
    if api_key:
        params["api_key"] = api_key

    try:
        response = requests.get(EFETCH_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred for PMCID {pmcid}: {str(e)}")
        if response.text:
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


def main():
    """Entry point for fetching article XML"""
    parser = argparse.ArgumentParser(
        description="Fetch article text from NCBI via E-utilities"
    )
    parser.add_argument("--pmcid", type=str, help="PMCID of the article to fetch")
    parser.add_argument(
        "--save_dir",
        default="data/articles",
        type=str,
        help="Path to save the article text",
    )
    args = parser.parse_args()

    if not args.pmcid:
        parser.error("--pmcid is required")

    text = get_html_from_pmcid(args.pmcid)
    if text is not None:
        with open(f"{args.save_dir}/{args.pmcid}.xml", "w") as f:
            f.write(text)


if __name__ == "__main__":
    main()
