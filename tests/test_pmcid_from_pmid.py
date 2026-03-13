"""Tests for PMID to PMCID resolution."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from pubmed_markdown.pmcid_from_pmid import (
    get_pmcid_from_pmid,
    _is_cache_entry_valid,
    _load_cache,
    _save_cache,
    _get_cache_file_path,
)


# ---------------------------------------------------------------------------
# Cache entry validation
# ---------------------------------------------------------------------------


def test_cache_entry_valid():
    entry = {"pmcid": "PMC123", "timestamp": datetime.now().isoformat()}
    assert _is_cache_entry_valid(entry, expiry_days=30) is True


def test_cache_entry_expired():
    old_time = (datetime.now() - timedelta(days=60)).isoformat()
    entry = {"pmcid": "PMC123", "timestamp": old_time}
    assert _is_cache_entry_valid(entry, expiry_days=30) is False


def test_cache_entry_no_timestamp():
    entry = {"pmcid": "PMC123"}
    assert _is_cache_entry_valid(entry) is False


def test_cache_entry_invalid_timestamp():
    entry = {"pmcid": "PMC123", "timestamp": "not-a-date"}
    assert _is_cache_entry_valid(entry) is False


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def test_load_cache_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "nonexistent.json")
    cache = _load_cache()
    assert cache == {}


def test_save_and_load_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test_cache.json")

    data = {"12345": {"pmcid": "PMC999", "timestamp": datetime.now().isoformat()}}
    _save_cache(data)

    loaded = _load_cache()
    assert loaded["12345"]["pmcid"] == "PMC999"


def test_load_cache_corrupted_json(tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "bad.json")
    (tmp_path / "bad.json").write_text("not valid json {{{")

    cache = _load_cache()
    assert cache == {}


# ---------------------------------------------------------------------------
# get_pmcid_from_pmid
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_single_pmid(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"records": [{"pmid": "12345", "pmcid": "PMC111"}]}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid("12345", email="test@test.com", use_cache=False)
    assert result["12345"] == "PMC111"


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_multiple_pmids(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

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

    result = get_pmcid_from_pmid(
        ["111", "222", "333"], email="test@test.com", use_cache=False
    )
    assert result["111"] == "PMC001"
    assert result["222"] == "PMC002"
    assert result["333"] is None


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_pmid_not_in_response(mock_get, tmp_path, monkeypatch):
    """PMIDs missing from the API response should map to None."""
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"records": []}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid("99999", email="test@test.com", use_cache=False)
    assert result["99999"] is None


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_api_failure_returns_none(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

    mock_get.side_effect = Exception("Network error")

    result = get_pmcid_from_pmid("12345", email="test@test.com", use_cache=False)
    assert result["12345"] is None


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_caching_avoids_api_call(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

    # Pre-populate cache
    cache_data = {"12345": {"pmcid": "PMC999", "timestamp": datetime.now().isoformat()}}
    (tmp_path / "test.json").write_text(json.dumps(cache_data))

    result = get_pmcid_from_pmid("12345", email="test@test.com", use_cache=True)
    assert result["12345"] == "PMC999"
    mock_get.assert_not_called()


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_expired_cache_triggers_api_call(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

    # Pre-populate cache with expired entry
    old_time = (datetime.now() - timedelta(days=60)).isoformat()
    cache_data = {"12345": {"pmcid": "PMC999", "timestamp": old_time}}
    (tmp_path / "test.json").write_text(json.dumps(cache_data))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "records": [{"pmid": "12345", "pmcid": "PMC_UPDATED"}]
    }
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid(
        "12345", email="test@test.com", use_cache=True, cache_expiry_days=30
    )
    assert result["12345"] == "PMC_UPDATED"
    mock_get.assert_called_once()


@patch("pubmed_markdown.pmcid_from_pmid.requests.get")
def test_whitespace_normalization(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("PMID_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PMID_CACHE_FILE", "test.json")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"records": [{"pmid": "12345", "pmcid": "PMC111"}]}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    result = get_pmcid_from_pmid("  12345  ", email="test@test.com", use_cache=False)
    assert result["12345"] == "PMC111"
