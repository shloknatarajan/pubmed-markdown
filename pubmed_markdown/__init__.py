from importlib.metadata import PackageNotFoundError, version

from .html_from_pmcid import get_html_from_pmcid
from .xml_from_pmcid import (
    get_xml_from_europe_pmc,
    get_xml_from_ncbi_efetch,
    get_xml_from_pmcid,
    is_xml_restricted,
    jats_has_full_text,
)
from .markdown_from_html import PubMedHTMLToMarkdownConverter
from .markdown_from_jats import JATSToMarkdownConverter
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
    __version__ = "0.3.0"

__all__ = [
    "PubMedMarkdown",
    "PubMedHTMLToMarkdownConverter",
    "JATSToMarkdownConverter",
    "get_html_from_pmcid",
    "get_xml_from_pmcid",
    "get_xml_from_ncbi_efetch",
    "get_xml_from_europe_pmc",
    "is_xml_restricted",
    "jats_has_full_text",
    "get_pmcid_from_pmid",
    "get_scraped_pmids",
    "fetch_bioc_supplement",
    "format_supplement_as_markdown",
    "get_abstract_markdown_from_pmid",
    "is_waf_or_captcha_html",
    "WAFChallengeError",
]
