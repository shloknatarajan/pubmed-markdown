"""
PMCID --> Full Article Text (HTML)
This uses a standard get request with a user agent and accept header to fetch the article text.
"""

import os
from importlib.metadata import version

import requests
from loguru import logger
from typing import Optional


def get_html_from_pmcid(pmcid: str, email: Optional[str] = None) -> Optional[str]:
    """
    Given a PMCID, fetch the full article text from the NCBI website.
    Returns the HTML text of the article in string format from the url
    https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=classic

    Args:
        pmcid (str): The PMCID to fetch
        email (str, optional): Email for NCBI identification. Falls back to NCBI_EMAIL env var.

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
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # This will raise an exception for 4XX/5XX status codes
        return response.text
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred for PMCID {pmcid}: {str(e)}")
        if response.text:
            logger.error(f"Server response: {response.text}")
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
