"""Tests for PMID to PMCID resolution."""

from unittest.mock import patch, MagicMock
import pytest

from pubmed_markdown.pmcid_from_pmid import get_pmcid_from_pmid


# ---------------------------------------------------------------------------
# get_pmcid_from_pmid
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_single_pmid(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"records": [{"pmid": "12345", "pmcid": "PMC111"}]}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid("12345", email="test@test.com")
    assert result["12345"] == "PMC111"


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_multiple_pmids(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "records": [
            {"pmid": "111", "pmcid": "PMC001"},
            {"pmid": "222", "pmcid": "PMC002"},
            {"pmid": "333"},  # No PMCID
        ]
    }
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid(["111", "222", "333"], email="test@test.com")
    assert result["111"] == "PMC001"
    assert result["222"] == "PMC002"
    assert result["333"] is None


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_pmid_not_in_response(mock_get):
    """PMIDs missing from the API response should map to None."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"records": []}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid("99999", email="test@test.com")
    assert result["99999"] is None


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_api_failure_returns_none(mock_get):
    mock_get.side_effect = Exception("Network error")

    result = get_pmcid_from_pmid("12345", email="test@test.com")
    assert result["12345"] is None


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_whitespace_normalization(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"records": [{"pmid": "12345", "pmcid": "PMC111"}]}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid("  12345  ", email="test@test.com")
    assert result["12345"] == "PMC111"
