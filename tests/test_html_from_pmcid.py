"""Tests for HTML fetching from PMCID."""

from unittest.mock import patch, MagicMock
import pytest
import requests

from pubmed_markdown.html_from_pmcid import get_html_from_pmcid


@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_successful_fetch(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>Article content</body></html>"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_html_from_pmcid("PMC1234567")
    assert result == "<html><body>Article content</body></html>"
    mock_get.assert_called_once()
    assert "PMC1234567" in mock_get.call_args[0][0]


@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_http_error(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not found"
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    mock_get.return_value = mock_resp

    result = get_html_from_pmcid("PMC0000000")
    assert result is None


@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_connection_error(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    result = get_html_from_pmcid("PMC1234567")
    assert result is None


@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_timeout_error(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")
    result = get_html_from_pmcid("PMC1234567")
    assert result is None


def test_non_string_input():
    result = get_html_from_pmcid(12345)
    assert result is None


@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_url_format(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html></html>"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    get_html_from_pmcid("PMC7654321")
    url = mock_get.call_args[0][0]
    assert url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7654321/?report=classic"
