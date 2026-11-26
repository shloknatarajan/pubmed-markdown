"""Structured result and error models for article fetching."""

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

TierName = Literal[
    "id_converter",
    "ncbi_xml",
    "europe_pmc_xml",
    "pmc_html",
    "pubmed_abstract",
    "bioc_supplement",
]

SourceTier = Literal[
    "ncbi_xml",
    "europe_pmc_xml",
    "pmc_html",
    "pubmed_abstract",
]

ErrorCode = Literal[
    "no_pmcid",
    "xml_restricted",
    "no_full_text_body",
    "not_found",
    "waf_blocked",
    "http_error",
    "timeout",
    "connection_error",
    "request_error",
    "parse_error",
    "empty_output",
    "invalid_input",
]


@dataclass(frozen=True)
class TierError:
    """Structured diagnostic describing why a single upstream fetch tier failed."""

    tier: TierName
    code: ErrorCode
    message: str
    status_code: Optional[int] = None


@dataclass(frozen=True)
class FetchResult:
    """
    Structured result from fetching and converting a PubMed / PMC article.

    Attributes:
        markdown: Converted markdown content, or None if all attempted tiers failed.
        source: The exact upstream tier that produced `markdown`, or None on failure.
        pmid: Input PMID (if fetched by PMID).
        pmcid: Input or resolved PMCID (if available).
        has_supplements: True if BioC supplementary material text was appended.
        is_abstract_only: True if `markdown` is a PubMed abstract fallback rather than full text.
        errors: Ordered tuple of `TierError` objects recorded across every tier that failed
            (preserved even when a later tier or abstract fallback succeeds).
    """

    markdown: Optional[str]
    source: Optional[SourceTier] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    has_supplements: bool = False
    is_abstract_only: bool = False
    errors: Tuple[TierError, ...] = ()

    @property
    def ok(self) -> bool:
        """Return True if markdown content was successfully produced."""
        return self.markdown is not None

    @property
    def error_summary(self) -> Optional[str]:
        """Return a concise human-readable summary of recorded tier errors, or None if empty."""
        if not self.errors:
            return None
        return "; ".join(
            f"{err.tier} ({err.code}): {err.message}" for err in self.errors
        )
