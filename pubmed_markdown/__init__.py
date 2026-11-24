from importlib.metadata import PackageNotFoundError, version

from .html_from_pmcid import get_html_from_pmcid
from .http_utils import WAFChallengeError, is_waf_or_captcha_html
from .pmcid_from_pmid import get_pmcid_from_pmid
from .manage_records import get_scraped_pmids
from .core import PubMedMarkdown
from .utils_bioc import (
    fetch_bioc_supplement,
    format_supplement_as_markdown,
)
from .abstract_from_pmid import get_abstract_markdown_from_pmid

try:
    __version__ = version("pubmed-markdown")
except PackageNotFoundError:
    __version__ = "0.2.4"

__all__ = [
    "PubMedMarkdown",
    "get_html_from_pmcid",
    "get_pmcid_from_pmid",
    "get_scraped_pmids",
    "fetch_bioc_supplement",
    "format_supplement_as_markdown",
    "get_abstract_markdown_from_pmid",
    "is_waf_or_captcha_html",
    "WAFChallengeError",
]
