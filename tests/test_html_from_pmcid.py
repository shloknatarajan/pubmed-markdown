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


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_connection_error(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    result = get_html_from_pmcid("PMC1234567")
    assert result is None
    assert mock_get.call_count == 3


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_timeout_error(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")
    result = get_html_from_pmcid("PMC1234567")
    assert result is None
    assert mock_get.call_count == 3


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
    assert mock_get.call_args.kwargs["timeout"] == 30.0


@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_custom_timeout(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>Article</body></html>"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    get_html_from_pmcid("PMC7654321", timeout=12.5)
    assert mock_get.call_args.kwargs["timeout"] == 12.5


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_waf_captcha_http_200_rejected_after_retries(mock_get, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<html><head><title>Checking your browser - reCAPTCHA</title></head>"
        "<body>Please wait</body></html>"
    )
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_html_from_pmcid("PMC13717721")
    assert result is None
    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_transient_waf_captcha_recovers_on_retry(mock_get, mock_sleep):
    waf_resp = MagicMock(
        status_code=200,
        text="<html><head><title>Checking your browser - reCAPTCHA</title></head></html>",
    )
    ok_resp = MagicMock(
        status_code=200,
        text='<html><head><meta name="citation_title" content="Real Paper"></head><body>ok</body></html>',
    )
    ok_resp.raise_for_status.return_value = None
    mock_get.side_effect = [waf_resp, ok_resp]

    result = get_html_from_pmcid("PMC13729000")
    assert result is not None
    assert "Real Paper" in result
    assert mock_get.call_count == 2
    assert mock_sleep.call_count == 1


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_empty_html_rejected(mock_get, mock_sleep):
    mock_resp = MagicMock(status_code=200, text="   ")
    mock_get.return_value = mock_resp

    result = get_html_from_pmcid("PMC1234567", max_retries=0)
    assert result is None
    assert mock_get.call_count == 1


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_403_not_retried(mock_get, mock_sleep):
    mock_resp = MagicMock(status_code=403, text="Forbidden")
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("403")
    mock_get.return_value = mock_resp

    result = get_html_from_pmcid("PMC13717721")
    assert result is None
    assert mock_get.call_count == 1
    mock_sleep.assert_not_called()


@patch("pubmed_markdown.http_utils.time.sleep")
@patch("pubmed_markdown.html_from_pmcid.requests.get")
def test_429_retries_with_retry_after(mock_get, mock_sleep):
    resp_429 = MagicMock(
        status_code=429, headers={"Retry-After": "4"}, text="Rate limit"
    )
    resp_200 = MagicMock(
        status_code=200,
        headers={},
        text="<html><body>Recovered article</body></html>",
    )
    resp_200.raise_for_status.return_value = None
    mock_get.side_effect = [resp_429, resp_200]

    result = get_html_from_pmcid("PMC13735422")
    assert result == "<html><body>Recovered article</body></html>"
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(4.0)
