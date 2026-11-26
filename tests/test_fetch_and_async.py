"""Tests for FetchResult, TierError, async fetch APIs, and api.py integration."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
import requests

from pubmed_markdown import (
    AsyncRateGate,
    FetchResult,
    PubMedMarkdown,
    TierError,
)
from pubmed_markdown.http_utils import WAFChallengeError

SAMPLE_JATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article>
    <front>
      <article-meta>
        <article-id pub-id-type="pmid">11111111</article-id>
        <article-id pub-id-type="pmc">5555555</article-id>
        <title-group><article-title>Structured Fetch Test Article</article-title></title-group>
        <abstract><p>JATS abstract content.</p></abstract>
      </article-meta>
    </front>
    <body>
      <sec id="sec1">
        <title>Introduction</title>
        <p>JATS body paragraph.</p>
      </sec>
    </body>
  </article>
</pmc-articleset>
"""

RESTRICTED_JATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article>
    <!--The publisher of this article does not allow downloading of the full text in XML form.-->
    <front>
      <article-meta>
        <title-group><article-title>Restricted Article</article-title></title-group>
      </article-meta>
    </front>
  </article>
</pmc-articleset>
"""

SAMPLE_HTML = """
<html>
<head>
    <meta name="citation_title" content="HTML Fallback Article">
    <meta name="citation_pmid" content="11111111">
    <link rel="canonical" href="https://pmc.ncbi.nlm.nih.gov/articles/PMC5555555/">
</head>
<body>
<section class="abstract"><p>HTML abstract.</p></section>
<section class="main-article-body">
    <section id="sec1">
        <h2 class="pmc_sec_title">Introduction</h2>
        <p>HTML intro text.</p>
    </section>
</section>
</body>
</html>
"""

EFETCH_ABSTRACT_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Abstract Fallback Title</ArticleTitle>
        <Journal><Title>Test Journal</Title></Journal>
        <Abstract>
          <AbstractText>Abstract fallback body.</AbstractText>
        </Abstract>
        <PubDate><Year>2025</Year></PubDate>
      </Article>
    </MedlineCitation>
    <PubmedData/>
  </PubmedArticle>
</PubmedArticleSet>
"""


# ---------------------------------------------------------------------------
# FetchResult & TierError diagnostics
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.format_supplement_as_markdown", return_value=None)
@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_fetch_pmcid_succeeds_via_ncbi_xml(mock_get, mock_supp):
    resp = MagicMock(status_code=200, text=SAMPLE_JATS_XML, headers={})
    resp.raise_for_status.return_value = None
    mock_get.return_value = resp

    converter = PubMedMarkdown(email="test@example.com")
    result = converter.fetch_pmcid("PMC5555555")

    assert isinstance(result, FetchResult)
    assert result.ok is True
    assert result.source == "ncbi_xml"
    assert result.pmcid == "PMC5555555"
    assert result.has_supplements is False
    assert result.is_abstract_only is False
    assert result.errors == ()
    assert result.error_summary is None
    assert "# Structured Fetch Test Article" in result.markdown


@patch(
    "pubmed_markdown.core.format_supplement_as_markdown",
    return_value="## Supplementary Materials\n\n### supp.pdf\n\nExtra data.",
)
@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_fetch_pmcid_records_xml_restricted_and_falls_back_to_europe_pmc(
    mock_get, mock_supp
):
    ncbi_resp = MagicMock(status_code=200, text=RESTRICTED_JATS_XML, headers={})
    ncbi_resp.raise_for_status.return_value = None
    epmc_resp = MagicMock(status_code=200, text=SAMPLE_JATS_XML, headers={})
    epmc_resp.raise_for_status.return_value = None
    mock_get.side_effect = [ncbi_resp, epmc_resp]

    converter = PubMedMarkdown(email="test@example.com")
    result = converter.fetch_pmcid("PMC5555555", include_supplements=True)

    assert result.ok is True
    assert result.source == "europe_pmc_xml"
    assert result.has_supplements is True
    assert "Extra data." in result.markdown
    assert len(result.errors) == 1
    assert result.errors[0].tier == "ncbi_xml"
    assert result.errors[0].code == "xml_restricted"


@patch("pubmed_markdown.core.format_supplement_as_markdown", return_value=None)
@patch("requests.get")
def test_fetch_pmcid_falls_back_to_pmc_html_and_preserves_xml_errors(
    mock_get, mock_supp
):
    def router(url, **kwargs):
        if "eutils.ncbi.nlm.nih.gov" in url:
            r = MagicMock(status_code=200, text=RESTRICTED_JATS_XML, headers={})
            r.raise_for_status.return_value = None
            return r
        if "ebi.ac.uk" in url:
            return MagicMock(status_code=404, text="", headers={})
        if "pmc.ncbi.nlm.nih.gov" in url:
            r = MagicMock(status_code=200, text=SAMPLE_HTML, headers={})
            r.raise_for_status.return_value = None
            return r
        raise AssertionError(f"Unexpected URL: {url}")

    mock_get.side_effect = router

    converter = PubMedMarkdown(email="test@example.com")
    result = converter.fetch_pmcid("PMC5555555")

    assert result.ok is True
    assert result.source == "pmc_html"
    assert "# HTML Fallback Article" in result.markdown
    assert [(e.tier, e.code, e.status_code) for e in result.errors] == [
        ("ncbi_xml", "xml_restricted", None),
        ("europe_pmc_xml", "not_found", 404),
    ]


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("requests.get")
def test_fetch_pmcid_all_tiers_fail_surfaces_exact_codes(mock_get, mock_sleep):
    def router(url, **kwargs):
        if "eutils.ncbi.nlm.nih.gov" in url:
            r = MagicMock(status_code=200, text=RESTRICTED_JATS_XML, headers={})
            r.raise_for_status.return_value = None
            return r
        if "ebi.ac.uk" in url:
            return MagicMock(status_code=404, text="", headers={})
        if "pmc.ncbi.nlm.nih.gov" in url:
            r = MagicMock(
                status_code=200,
                text="<html><head><title>Checking your browser - reCAPTCHA</title></head><body>Verify you are human</body></html>",
                headers={},
            )
            r.raise_for_status.return_value = None
            return r
        raise AssertionError(f"Unexpected URL: {url}")

    mock_get.side_effect = router

    converter = PubMedMarkdown(email="test@example.com")
    result = converter.fetch_pmcid("PMC5555555")

    assert result.ok is False
    assert result.markdown is None
    assert result.source is None
    assert [(e.tier, e.code) for e in result.errors] == [
        ("ncbi_xml", "xml_restricted"),
        ("europe_pmc_xml", "not_found"),
        ("pmc_html", "waf_blocked"),
    ]
    assert result.error_summary is not None
    assert "xml_restricted" in result.error_summary
    assert "waf_blocked" in result.error_summary


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("requests.get")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_fetch_pmid_abstract_fallback_preserves_full_text_errors(
    mock_idconv, mock_get, mock_sleep
):
    mock_idconv.return_value = {"11111111": "PMC5555555"}

    def router(url, **kwargs):
        params = kwargs.get("params") or {}
        if "eutils.ncbi.nlm.nih.gov" in url and params.get("db") == "pmc":
            r = MagicMock(status_code=200, text=RESTRICTED_JATS_XML, headers={})
            r.raise_for_status.return_value = None
            return r
        if "ebi.ac.uk" in url:
            return MagicMock(status_code=404, text="", headers={})
        if "pmc.ncbi.nlm.nih.gov" in url:
            r = MagicMock(status_code=403, text="Forbidden", headers={})
            r.raise_for_status.side_effect = requests.exceptions.HTTPError(
                "403 Client Error: Forbidden"
            )
            return r
        if "eutils.ncbi.nlm.nih.gov" in url and params.get("db") == "pubmed":
            r = MagicMock(status_code=200, text=EFETCH_ABSTRACT_XML, headers={})
            r.raise_for_status.return_value = None
            return r
        raise AssertionError(f"Unexpected request: {url} {params}")

    mock_get.side_effect = router

    converter = PubMedMarkdown(email="test@example.com")
    result = converter.fetch_pmid("11111111", fallback_to_abstract=True)

    assert result.ok is True
    assert result.source == "pubmed_abstract"
    assert result.is_abstract_only is True
    assert result.pmid == "11111111"
    assert result.pmcid == "PMC5555555"
    assert "# Abstract Fallback Title" in result.markdown
    assert [(e.tier, e.code, e.status_code) for e in result.errors] == [
        ("ncbi_xml", "xml_restricted", None),
        ("europe_pmc_xml", "not_found", 404),
        ("pmc_html", "http_error", 403),
    ]


@patch("pubmed_markdown.core.get_pmcid_from_pmid", return_value={"99999": None})
def test_fetch_pmid_no_pmcid_and_no_fallback_returns_no_pmcid_error(mock_idconv):
    converter = PubMedMarkdown(email="test@example.com")
    result = converter.fetch_pmid("99999", fallback_to_abstract=False)

    assert result.ok is False
    assert result.markdown is None
    assert result.pmcid is None
    assert result.is_abstract_only is False
    assert len(result.errors) == 1
    assert result.errors[0].tier == "id_converter"
    assert result.errors[0].code == "no_pmcid"


# ---------------------------------------------------------------------------
# Async APIs on PubMedMarkdown
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.format_supplement_as_markdown", return_value=None)
@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_afetch_pmcid_and_apmcid_to_markdown(mock_get, mock_supp):
    resp = MagicMock(status_code=200, text=SAMPLE_JATS_XML, headers={})
    resp.raise_for_status.return_value = None
    mock_get.return_value = resp

    gate = AsyncRateGate(concurrency=2, min_interval=0.0)
    converter = PubMedMarkdown(email="test@example.com", rate_gate=gate)

    async def run():
        res = await converter.afetch_pmcid("PMC5555555")
        md_single = await converter.apmcid_to_markdown("PMC5555555")
        md_batch = await converter.apmcid_to_markdown(["PMC5555555", "PMC6666666"])
        empty_batch = await converter.afetch_pmcids([])
        return res, md_single, md_batch, empty_batch

    res, md_single, md_batch, empty_batch = asyncio.run(run())

    assert res.ok is True
    assert res.source == "ncbi_xml"
    assert "# Structured Fetch Test Article" in md_single
    assert len(md_batch) == 2
    assert all("# Structured Fetch Test Article" in m for m in md_batch)
    assert empty_batch == []


@patch("pubmed_markdown.core.format_supplement_as_markdown", return_value=None)
@patch("requests.get")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_afetch_pmids_batches_id_lookup_and_preserves_order(
    mock_idconv, mock_get, mock_supp
):
    mock_idconv.return_value = {"111": "PMC5555555", "222": None}

    def router(url, **kwargs):
        params = kwargs.get("params") or {}
        if params.get("db") == "pmc":
            r = MagicMock(status_code=200, text=SAMPLE_JATS_XML, headers={})
            r.raise_for_status.return_value = None
            return r
        if params.get("db") == "pubmed":
            r = MagicMock(status_code=200, text=EFETCH_ABSTRACT_XML, headers={})
            r.raise_for_status.return_value = None
            return r
        raise AssertionError(f"Unexpected request: {url} {params}")

    mock_get.side_effect = router

    gate = AsyncRateGate(concurrency=4, min_interval=0.0)
    converter = PubMedMarkdown(email="test@example.com", rate_gate=gate)

    async def run():
        results = await converter.afetch_pmids(["111", "222"])
        mds = await converter.apmid_to_markdown(["111", "222"])
        empty = await converter.afetch_pmids([])
        return results, mds, empty

    results, mds, empty = asyncio.run(run())

    # Each batch call should perform exactly ONE batched ID lookup
    assert mock_idconv.call_count == 2
    assert results[0].pmid == "111"
    assert results[0].source == "ncbi_xml"
    assert results[0].is_abstract_only is False
    assert results[1].pmid == "222"
    assert results[1].source == "pubmed_abstract"
    assert results[1].is_abstract_only is True
    assert len(mds) == 2
    assert "# Structured Fetch Test Article" in mds[0]
    assert "# Abstract Fallback Title" in mds[1]
    assert empty == []


# ---------------------------------------------------------------------------
# api.py dogfooding FetchResult + AsyncRateGate
# ---------------------------------------------------------------------------


def test_api_convert_helpers_use_fetch_result_and_surface_errors():
    fastapi = pytest.importorskip("fastapi")
    assert fastapi is not None

    import api

    fake_failure = FetchResult(
        markdown=None,
        source=None,
        pmcid="PMC5555555",
        errors=(
            TierError(
                tier="ncbi_xml",
                code="xml_restricted",
                message="Publisher restricts XML download",
            ),
            TierError(
                tier="pmc_html",
                code="waf_blocked",
                message="AWS WAF challenge",
            ),
        ),
    )

    with patch.object(
        PubMedMarkdown, "afetch_pmcid", return_value=fake_failure
    ) as mock_afetch:
        res = asyncio.run(api._convert_pmcid("PMC5555555"))

    mock_afetch.assert_called_once()
    assert res.markdown is None
    assert res.pmcid == "PMC5555555"
    assert res.source is None
    assert res.error is not None
    assert "xml_restricted" in res.error
    assert [e.code for e in res.errors] == ["xml_restricted", "waf_blocked"]
