"""Tests for PubMedMarkdown core class — integration of all conversion paths."""

import os
import json
from unittest.mock import patch, MagicMock
import pytest

from pubmed_markdown.core import PubMedMarkdown, convert_pmids_from_file


SAMPLE_HTML = """
<html>
<head>
    <meta name="citation_title" content="Test Article">
    <meta name="citation_pmid" content="11111111">
    <link rel="canonical" href="https://pmc.ncbi.nlm.nih.gov/articles/PMC5555555/">
</head>
<body>
<section class="abstract"><p>Test abstract content.</p></section>
<section class="main-article-body">
    <section id="sec1">
        <h2 class="pmc_sec_title">Introduction</h2>
        <p>Intro text.</p>
    </section>
</section>
</body>
</html>
"""

EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Abstract Only Article</ArticleTitle>
        <Journal><Title>Some Journal</Title></Journal>
        <Abstract>
          <AbstractText>Abstract-only content here.</AbstractText>
        </Abstract>
        <ArticleDate><Year>2024</Year></ArticleDate>
      </Article>
    </MedlineCitation>
    <PubmedData/>
  </PubmedArticle>
</PubmedArticleSet>
"""


@pytest.fixture
def converter():
    return PubMedMarkdown(email="test@test.com")


# ---------------------------------------------------------------------------
# pmcids_to_markdown (single + list)
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_markdown_single(mock_html, mock_supp, converter):
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = None

    md = converter.pmcids_to_markdown("PMC5555555")
    assert isinstance(md, str)
    assert "# Test Article" in md
    assert "## Abstract" in md
    assert "Test abstract content." in md
    assert "## Introduction" in md


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_markdown_list(mock_html, mock_supp, converter):
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = None

    results = converter.pmcids_to_markdown(["PMC5555555", "PMC5555555"])
    assert isinstance(results, list)
    assert len(results) == 2
    assert all("# Test Article" in md for md in results)


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_markdown_with_supplements(mock_html, mock_supp, converter):
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = "## Supplementary Materials\n\n### table.pdf\n\nSupp data."

    md = converter.pmcids_to_markdown("PMC5555555", include_supplements=True)
    assert "## Supplementary Materials" in md
    assert "Supp data." in md


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_markdown_no_supplements_flag(mock_html, mock_supp, converter):
    mock_html.return_value = SAMPLE_HTML

    md = converter.pmcids_to_markdown("PMC5555555", include_supplements=False)
    assert md is not None
    mock_supp.assert_not_called()


@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_markdown_html_fetch_fails(mock_html, converter):
    mock_html.return_value = None
    md = converter.pmcids_to_markdown("PMC0000000")
    assert md is None


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_markdown_conversion_exception(mock_html, mock_supp, converter):
    mock_html.return_value = "<invalid html that will crash somehow>"
    with patch.object(
        converter.html_to_markdown, "convert_html", side_effect=Exception("parse error")
    ):
        md = converter.pmcids_to_markdown("PMC5555555")
        assert md is None


# ---------------------------------------------------------------------------
# pmid_to_markdown (single + list)
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_pmid_to_markdown_single_full_text(mock_pmcid, mock_html, mock_supp, converter):
    mock_pmcid.return_value = {"11111111": "PMC5555555"}
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = None

    md = converter.pmid_to_markdown("11111111")
    assert isinstance(md, str)
    assert "# Test Article" in md
    assert "## Introduction" in md


@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_pmid_to_markdown_list(mock_pmcid, mock_html, mock_supp, converter):
    mock_pmcid.return_value = {"11111111": "PMC5555555"}
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = None

    results = converter.pmid_to_markdown(["11111111"])
    assert isinstance(results, list)
    assert len(results) == 1
    assert "# Test Article" in results[0]


@patch("pubmed_markdown.core.get_abstract_markdown_from_pmid")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_pmid_to_markdown_abstract_fallback(mock_pmcid, mock_abstract, converter):
    """When no PMCID exists, falls back to abstract-only."""
    mock_pmcid.return_value = {"22222222": None}
    mock_abstract.return_value = "# Abstract Only Article\n\n## Abstract\n\nContent."

    md = converter.pmid_to_markdown("22222222")
    assert md is not None
    assert "Abstract Only Article" in md


@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_pmid_to_markdown_no_pmcid_no_abstract(mock_pmcid, converter):
    mock_pmcid.return_value = {"33333333": None}

    with patch(
        "pubmed_markdown.core.get_abstract_markdown_from_pmid", return_value=None
    ):
        md = converter.pmid_to_markdown("33333333")
        assert md is None


# ---------------------------------------------------------------------------
# pmids_to_markdown_files (batch, file-based)
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.get_abstract_markdown_from_pmid")
@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_pmids_to_markdown_files_batch(
    mock_pmcid, mock_html, mock_supp, mock_abstract, tmp_path
):
    """Full batch: one article with PMCID, one without."""
    mock_pmcid.return_value = {"111": "PMC001", "222": None}
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = None
    mock_abstract.return_value = "# Fallback\n\n## Abstract\n\nAbstract text."

    converter = PubMedMarkdown(save_dir=str(tmp_path), email="test@test.com")
    converter.pmids_to_markdown_files(["111", "222"], save_dir=str(tmp_path))

    md_dir = tmp_path / "markdown"
    assert md_dir.exists()

    # Full-text article saved as PMC001.md
    full_text_file = md_dir / "PMC001.md"
    assert full_text_file.exists()
    content = full_text_file.read_text()
    assert "Test Article" in content

    # Abstract-only article saved as PMID222.md
    abstract_file = md_dir / "PMID222.md"
    assert abstract_file.exists()
    content = abstract_file.read_text()
    assert "Fallback" in content


@patch("pubmed_markdown.core.get_abstract_markdown_from_pmid")
@patch("pubmed_markdown.core.format_supplement_as_markdown")
@patch("pubmed_markdown.core.get_html_from_pmcid")
@patch("pubmed_markdown.core.get_pmcid_from_pmid")
def test_pmids_to_markdown_files_single_string(
    mock_pmcid, mock_html, mock_supp, mock_abstract, tmp_path
):
    """Accepts a single PMID string."""
    mock_pmcid.return_value = {"111": "PMC001"}
    mock_html.return_value = SAMPLE_HTML
    mock_supp.return_value = None

    converter = PubMedMarkdown(email="test@test.com")
    converter.pmids_to_markdown_files("111", save_dir=str(tmp_path))

    md_dir = tmp_path / "markdown"
    assert (md_dir / "PMC001.md").exists()


# ---------------------------------------------------------------------------
# local_html_to_markdown
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.format_supplement_as_markdown")
def test_local_html_to_markdown(mock_supp, tmp_path):
    mock_supp.return_value = None

    # Create HTML directory with a test file
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    md_dir = tmp_path / "markdown"
    md_dir.mkdir()

    (html_dir / "PMC123.html").write_text(SAMPLE_HTML)

    converter = PubMedMarkdown(email="test@test.com")
    converter.local_html_to_markdown(save_dir=str(tmp_path))

    md_file = md_dir / "PMC123.md"
    assert md_file.exists()
    content = md_file.read_text()
    assert "# Test Article" in content


@patch("pubmed_markdown.core.format_supplement_as_markdown")
def test_local_html_to_markdown_no_overwrite(mock_supp, tmp_path):
    """Existing markdown files should not be overwritten by default."""
    mock_supp.return_value = None

    html_dir = tmp_path / "html"
    html_dir.mkdir()
    md_dir = tmp_path / "markdown"
    md_dir.mkdir()

    (html_dir / "PMC123.html").write_text(SAMPLE_HTML)
    (md_dir / "PMC123.md").write_text("existing content")

    converter = PubMedMarkdown(email="test@test.com")
    converter.local_html_to_markdown(save_dir=str(tmp_path), overwrite=False)

    content = (md_dir / "PMC123.md").read_text()
    assert content == "existing content"


def test_local_html_to_markdown_no_html_dir(tmp_path):
    converter = PubMedMarkdown(email="test@test.com")
    # Should not crash when html dir doesn't exist
    converter.local_html_to_markdown(save_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# check_existing_*_pmcids
# ---------------------------------------------------------------------------


def test_check_existing_html_pmcids(tmp_path):
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "PMC111.html").write_text("")
    (html_dir / "PMC222.html").write_text("")

    converter = PubMedMarkdown(email="test@test.com")
    pmcids = converter.check_existing_html_pmcids(str(tmp_path))
    assert set(pmcids) == {"PMC111", "PMC222"}


def test_check_existing_html_pmcids_no_dir(tmp_path):
    converter = PubMedMarkdown(email="test@test.com")
    assert converter.check_existing_html_pmcids(str(tmp_path)) == []


def test_check_existing_markdown_pmcids(tmp_path):
    md_dir = tmp_path / "markdown"
    md_dir.mkdir()
    (md_dir / "PMC111.md").write_text("")
    (md_dir / "PMC333.md").write_text("")

    converter = PubMedMarkdown(email="test@test.com")
    pmcids = converter.check_existing_markdown_pmcids(str(tmp_path))
    assert set(pmcids) == {"PMC111", "PMC333"}


# ---------------------------------------------------------------------------
# pmcids_to_html
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_html(mock_html, tmp_path):
    mock_html.return_value = "<html><body>Article</body></html>"

    converter = PubMedMarkdown(email="test@test.com")
    converter.pmcids_to_html(["PMC001", "PMC002"], save_dir=str(tmp_path))

    html_dir = tmp_path / "html"
    assert (html_dir / "PMC001.html").exists()
    assert (html_dir / "PMC002.html").exists()


@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_html_single_string(mock_html, tmp_path):
    mock_html.return_value = "<html><body>Article</body></html>"

    converter = PubMedMarkdown(email="test@test.com")
    converter.pmcids_to_html("PMC001", save_dir=str(tmp_path))

    html_dir = tmp_path / "html"
    assert (html_dir / "PMC001.html").exists()


@patch("pubmed_markdown.core.get_html_from_pmcid")
def test_pmcids_to_html_skips_existing(mock_html, tmp_path):
    mock_html.return_value = "<html><body>New</body></html>"

    html_dir = tmp_path / "html"
    html_dir.mkdir(parents=True)
    (html_dir / "PMC001.html").write_text("<html>Old</html>")

    converter = PubMedMarkdown(email="test@test.com")
    converter.pmcids_to_html(["PMC001", "PMC002"], save_dir=str(tmp_path))

    # PMC001 should not be re-fetched
    assert (html_dir / "PMC001.html").read_text() == "<html>Old</html>"
    # PMC002 should be fetched
    assert (html_dir / "PMC002.html").exists()


# ---------------------------------------------------------------------------
# convert_pmids_from_file
# ---------------------------------------------------------------------------


@patch("pubmed_markdown.core.PubMedMarkdown.pmids_to_markdown_files")
def test_convert_pmids_from_file(mock_method, tmp_path):
    pmid_file = tmp_path / "pmids.txt"
    pmid_file.write_text("111\n222\n333\n")

    convert_pmids_from_file(
        str(pmid_file), save_dir=str(tmp_path), email="test@test.com"
    )

    mock_method.assert_called_once()
    args = mock_method.call_args
    assert args[0][0] == ["111", "222", "333"]


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_constructor_with_email():
    pm = PubMedMarkdown(email="user@example.com")
    assert pm.email == "user@example.com"


def test_constructor_env_email(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "env@example.com")
    pm = PubMedMarkdown()
    assert pm.email == "env@example.com"


def test_constructor_no_email(monkeypatch):
    monkeypatch.delenv("NCBI_EMAIL", raising=False)
    # Should not raise, just warn
    pm = PubMedMarkdown()
    assert pm.email is None
