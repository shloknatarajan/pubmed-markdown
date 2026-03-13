"""Tests for BioC supplement fetching and formatting."""

import json
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from pubmed_markdown.utils_bioc import (
    fetch_bioc_supplement,
    format_supplement_as_markdown,
    _extract_text_from_bioc,
    _extract_text_from_bioc_structured,
)


# ---------------------------------------------------------------------------
# BioC JSON parsing
# ---------------------------------------------------------------------------

SAMPLE_BIOC_JSON = [
    {
        "source": "BioC",
        "documents": [
            {
                "id": "supplement_table1.pdf",
                "passages": [
                    {"offset": 0, "text": "Table S1: Patient demographics"},
                    {"offset": 100, "text": "Age range: 18-65 years"},
                ],
            },
            {
                "id": "supplement_figure1.pdf",
                "passages": [
                    {"offset": 0, "text": "Figure S1 caption: Survival curve"},
                ],
            },
        ],
    }
]


def test_extract_text_structured():
    docs = _extract_text_from_bioc_structured(SAMPLE_BIOC_JSON)
    assert len(docs) == 2
    assert docs[0]["filename"] == "supplement_table1.pdf"
    assert "Table S1" in docs[0]["text"]
    assert "Age range" in docs[0]["text"]
    assert docs[1]["filename"] == "supplement_figure1.pdf"
    assert "Survival curve" in docs[1]["text"]


def test_extract_text_flat():
    text = _extract_text_from_bioc(SAMPLE_BIOC_JSON)
    assert "Table S1" in text
    assert "Age range" in text
    assert "Survival curve" in text


def test_extract_text_dict_input():
    """Handle dict (single collection) instead of list."""
    single = SAMPLE_BIOC_JSON[0]
    docs = _extract_text_from_bioc_structured(single)
    assert len(docs) == 2


def test_extract_text_empty_passages():
    data = [{"source": "BioC", "documents": [{"id": "empty.pdf", "passages": []}]}]
    docs = _extract_text_from_bioc_structured(data)
    assert len(docs) == 0


def test_extract_text_no_documents():
    data = [{"source": "BioC", "documents": []}]
    docs = _extract_text_from_bioc_structured(data)
    assert len(docs) == 0


def test_extract_text_malformed_input():
    docs = _extract_text_from_bioc_structured("not a list or dict")
    assert docs == []


# ---------------------------------------------------------------------------
# fetch_bioc_supplement
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_fetch_supplement_success(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps(SAMPLE_BIOC_JSON)
    mock_get.return_value = mock_resp

    text = fetch_bioc_supplement("PMC1234", use_cache=False)
    assert text is not None
    assert "Table S1" in text


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_fetch_supplement_not_available(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    text = fetch_bioc_supplement("PMC0000", use_cache=False)
    assert text is None


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_fetch_supplement_empty_response(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_get.return_value = mock_resp

    text = fetch_bioc_supplement("PMC0000", use_cache=False)
    assert text is None


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_fetch_supplement_html_response(mock_get, tmp_path, monkeypatch):
    """API returns HTML when no supplements — should handle gracefully."""
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>No supplements</body></html>"
    mock_get.return_value = mock_resp

    text = fetch_bioc_supplement("PMC0000", use_cache=False)
    assert text is None


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_fetch_supplement_caching(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps(SAMPLE_BIOC_JSON)
    mock_get.return_value = mock_resp

    # First call — fetches from API
    text1 = fetch_bioc_supplement("PMC1234", use_cache=True)
    assert text1 is not None
    assert mock_get.call_count == 1

    # Second call — should use cache
    text2 = fetch_bioc_supplement("PMC1234", use_cache=True)
    assert text2 == text1
    assert mock_get.call_count == 1  # No additional API call


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_fetch_supplement_network_error(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)
    import requests

    mock_get.side_effect = requests.exceptions.ConnectionError("fail")

    text = fetch_bioc_supplement("PMC1234", use_cache=False)
    assert text is None


# ---------------------------------------------------------------------------
# format_supplement_as_markdown
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_format_supplement_markdown(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps(SAMPLE_BIOC_JSON)
    mock_get.return_value = mock_resp

    md = format_supplement_as_markdown("PMC1234", use_cache=False)
    assert md is not None
    assert "## Supplementary Materials" in md
    assert "### supplement_table1.pdf" in md
    assert "Table S1" in md
    assert "### supplement_figure1.pdf" in md
    assert "Survival curve" in md


@patch("pubmed_markdown.utils_bioc.requests.get")
def test_format_supplement_none_when_unavailable(mock_get, tmp_path, monkeypatch):
    monkeypatch.setattr("pubmed_markdown.utils_bioc.CACHE_DIR", tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    md = format_supplement_as_markdown("PMC0000", use_cache=False)
    assert md is None
