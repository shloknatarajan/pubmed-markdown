"""Tests for JATS XML fetching from NCBI E-utilities and Europe PMC."""

from unittest.mock import MagicMock, patch

import requests

from pubmed_markdown.xml_from_pmcid import (
    EUROPE_PMC_DEFAULT_TIMEOUT,
    get_xml_from_europe_pmc,
    get_xml_from_ncbi_efetch,
    get_xml_from_pmcid,
    is_xml_restricted,
    jats_has_full_text,
    normalize_pmcid,
)

FULL_TEXT_JATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article>
    <front>
      <article-meta>
        <article-id pub-id-type="pmc">13729000</article-id>
        <title-group><article-title>Sample OA Article</article-title></title-group>
      </article-meta>
    </front>
    <body>
      <sec><title>Introduction</title><p>Full text body content here.</p></sec>
    </body>
  </article>
</pmc-articleset>
"""

PUBLISHER_RESTRICTED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article>
    <front>
      <article-meta>
        <article-id pub-id-type="pmc">13717721</article-id>
        <title-group><article-title>Restricted Article</article-title></title-group>
        <abstract><p>Abstract only.</p></abstract>
      </article-meta>
    </front>
    <!--The publisher of this article does not allow downloading of the full text in XML form.-->
  </article>
</pmc-articleset>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_normalize_pmcid():
    assert normalize_pmcid("PMC12345") == "PMC12345"
    assert normalize_pmcid("pmc12345") == "PMC12345"
    assert normalize_pmcid("12345") == "PMC12345"
    assert normalize_pmcid("  PMC999  ") == "PMC999"


def test_is_xml_restricted():
    assert is_xml_restricted(PUBLISHER_RESTRICTED_XML) is True
    assert is_xml_restricted(FULL_TEXT_JATS_XML) is False
    assert is_xml_restricted("") is False


def test_jats_has_full_text():
    assert jats_has_full_text(FULL_TEXT_JATS_XML) is True
    assert jats_has_full_text(PUBLISHER_RESTRICTED_XML) is False
    assert jats_has_full_text("<article><body>   </body></article>") is False
    assert jats_has_full_text("<article><body/></article>") is False
    assert jats_has_full_text("<error>not found</error>") is False
    assert jats_has_full_text("") is False


# ---------------------------------------------------------------------------
# NCBI E-utilities efetch
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_ncbi_efetch_success_with_key(mock_get, monkeypatch):
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    mock_resp = MagicMock(status_code=200, text=FULL_TEXT_JATS_XML)
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    xml = get_xml_from_ncbi_efetch(
        "PMC13729000", email="test@test.com", ncbi_key="my-ncbi-key", timeout=20.0
    )
    assert xml == FULL_TEXT_JATS_XML
    params = mock_get.call_args.kwargs["params"]
    assert params["db"] == "pmc"
    assert params["id"] == "13729000"
    assert params["retmode"] == "xml"
    assert params["email"] == "test@test.com"
    assert params["api_key"] == "my-ncbi-key"
    assert mock_get.call_args.kwargs["timeout"] == 20.0


@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_ncbi_efetch_reads_env_api_key(mock_get, monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "env-ncbi-key")
    mock_resp = MagicMock(status_code=200, text=FULL_TEXT_JATS_XML)
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    xml = get_xml_from_ncbi_efetch("PMC13729000", email="test@test.com")
    assert xml is not None
    assert mock_get.call_args.kwargs["params"]["api_key"] == "env-ncbi-key"


@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_ncbi_efetch_publisher_restricted_returns_none_by_default(mock_get):
    mock_resp = MagicMock(status_code=200, text=PUBLISHER_RESTRICTED_XML)
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    assert get_xml_from_ncbi_efetch("PMC13717721", email="test@test.com") is None
    # When require_full_text=False, returns metadata/abstract XML
    xml = get_xml_from_ncbi_efetch(
        "PMC13717721", email="test@test.com", require_full_text=False
    )
    assert xml == PUBLISHER_RESTRICTED_XML


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_ncbi_efetch_retries_on_429(mock_get, mock_sleep):
    resp_429 = MagicMock(status_code=429, headers={"Retry-After": "1"})
    resp_200 = MagicMock(status_code=200, text=FULL_TEXT_JATS_XML)
    resp_200.raise_for_status.return_value = None
    mock_get.side_effect = [resp_429, resp_200]

    xml = get_xml_from_ncbi_efetch("PMC13729000", email="test@test.com")
    assert xml == FULL_TEXT_JATS_XML
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_ncbi_efetch_network_error(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.ConnectionError("reset")
    assert get_xml_from_ncbi_efetch("PMC13729000") is None


def test_ncbi_efetch_invalid_input():
    assert get_xml_from_ncbi_efetch(12345) is None
    assert get_xml_from_ncbi_efetch("   ") is None


# ---------------------------------------------------------------------------
# Europe PMC fullTextXML
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_europe_pmc_success(mock_get):
    mock_resp = MagicMock(status_code=200, text=FULL_TEXT_JATS_XML)
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    xml = get_xml_from_europe_pmc("PMC13729000")
    assert xml == FULL_TEXT_JATS_XML
    assert (
        mock_get.call_args[0][0]
        == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13729000/fullTextXML"
    )
    assert mock_get.call_args.kwargs["timeout"] == EUROPE_PMC_DEFAULT_TIMEOUT


@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_europe_pmc_404_returns_none(mock_get):
    mock_resp = MagicMock(status_code=404, text="Not Found")
    mock_get.return_value = mock_resp

    assert get_xml_from_europe_pmc("PMC0000000") is None
    assert mock_get.call_count == 1


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.xml_from_pmcid.requests.get")
def test_europe_pmc_tls_reset_returns_none(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.SSLError("TLS reset")
    assert get_xml_from_europe_pmc("PMC13729000") is None


# ---------------------------------------------------------------------------
# Combined get_xml_from_pmcid (NCBI -> Europe PMC fallback)
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.xml_from_pmcid.get_xml_from_europe_pmc")
@patch("pubmed_markdown.xml_from_pmcid.get_xml_from_ncbi_efetch")
def test_get_xml_from_pmcid_uses_ncbi_first(mock_ncbi, mock_epmc):
    mock_ncbi.return_value = FULL_TEXT_JATS_XML

    xml = get_xml_from_pmcid("PMC13729000", email="test@test.com")
    assert xml == FULL_TEXT_JATS_XML
    mock_ncbi.assert_called_once()
    mock_epmc.assert_not_called()


@patch("pubmed_markdown.xml_from_pmcid.get_xml_from_europe_pmc")
@patch("pubmed_markdown.xml_from_pmcid.get_xml_from_ncbi_efetch")
def test_get_xml_from_pmcid_falls_back_to_europe_pmc(mock_ncbi, mock_epmc):
    mock_ncbi.return_value = None
    mock_epmc.return_value = FULL_TEXT_JATS_XML

    xml = get_xml_from_pmcid("PMC13729000", email="test@test.com")
    assert xml == FULL_TEXT_JATS_XML
    mock_ncbi.assert_called_once()
    mock_epmc.assert_called_once()


@patch("pubmed_markdown.xml_from_pmcid.get_xml_from_europe_pmc")
@patch("pubmed_markdown.xml_from_pmcid.get_xml_from_ncbi_efetch")
def test_get_xml_from_pmcid_disables_europe_pmc_fallback(mock_ncbi, mock_epmc):
    mock_ncbi.return_value = None

    xml = get_xml_from_pmcid(
        "PMC13729000", email="test@test.com", use_europe_pmc_fallback=False
    )
    assert xml is None
    mock_epmc.assert_not_called()
