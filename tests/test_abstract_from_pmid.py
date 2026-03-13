"""Tests for abstract fetching from PMID."""

from unittest.mock import patch, MagicMock
import pytest

from pubmed_markdown.abstract_from_pmid import (
    get_abstract_markdown_from_pmid,
    _get_element_text,
)


EFETCH_XML_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Test Drug Interaction Study</ArticleTitle>
        <AuthorList>
          <Author><ForeName>Alice</ForeName><LastName>Smith</LastName></Author>
          <Author><ForeName>Bob</ForeName><LastName>Jones</LastName></Author>
        </AuthorList>
        <Journal>
          <Title>Journal of Clinical Pharmacology</Title>
        </Journal>
        <Abstract>
          <AbstractText>This study investigated drug interactions.</AbstractText>
        </Abstract>
        <ArticleDate><Year>2023</Year></ArticleDate>
      </Article>
      <ArticleIdList>
        <ArticleId IdType="doi">10.9999/jcp.2023</ArticleId>
      </ArticleIdList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.9999/jcp.2023</ArticleId>
      </ArticleIdList>
      <History>
        <PubMedPubDate PubStatus="pubmed">
          <Year>2023</Year>
        </PubMedPubDate>
      </History>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

STRUCTURED_ABSTRACT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Structured Abstract Study</ArticleTitle>
        <AuthorList>
          <Author><ForeName>Carol</ForeName><LastName>White</LastName></Author>
        </AuthorList>
        <Journal><Title>Nature Medicine</Title></Journal>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background info here.</AbstractText>
          <AbstractText Label="METHODS">Methods info here.</AbstractText>
          <AbstractText Label="RESULTS">Results info here.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Conclusions info here.</AbstractText>
        </Abstract>
        <ArticleDate><Year>2024</Year></ArticleDate>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1038/nm.2024</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

NO_ABSTRACT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <ArticleTitle>Letter to the Editor</ArticleTitle>
        <Journal><Title>BMJ</Title></Journal>
      </Article>
    </MedlineCitation>
    <PubmedData/>
  </PubmedArticle>
</PubmedArticleSet>
"""


@patch("pubmed_markdown.abstract_from_pmid.requests.get")
def test_simple_abstract(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = EFETCH_XML_RESPONSE
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    md = get_abstract_markdown_from_pmid("11111111", email="test@test.com")
    assert md is not None
    assert "# Test Drug Interaction Study" in md
    assert "Alice Smith" in md
    assert "Bob Jones" in md
    assert "Journal of Clinical Pharmacology" in md
    assert "PMID: 11111111" in md
    assert "DOI: 10.9999/jcp.2023" in md
    assert "## Abstract" in md
    assert "This study investigated drug interactions." in md
    assert "not available on PubMed Central" in md


@patch("pubmed_markdown.abstract_from_pmid.requests.get")
def test_structured_abstract(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = STRUCTURED_ABSTRACT_XML
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    md = get_abstract_markdown_from_pmid("22222222", email="test@test.com")
    assert md is not None
    assert "**BACKGROUND:** Background info here." in md
    assert "**METHODS:** Methods info here." in md
    assert "**RESULTS:** Results info here." in md
    assert "**CONCLUSIONS:** Conclusions info here." in md


@patch("pubmed_markdown.abstract_from_pmid.requests.get")
def test_no_abstract_available(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = NO_ABSTRACT_XML
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    md = get_abstract_markdown_from_pmid("33333333", email="test@test.com")
    assert md is not None
    assert "No abstract available." in md


@patch("pubmed_markdown.abstract_from_pmid.requests.get")
def test_api_failure(mock_get):
    import requests

    mock_get.side_effect = requests.exceptions.ConnectionError("fail")
    md = get_abstract_markdown_from_pmid("44444444", email="test@test.com")
    assert md is None


@patch("pubmed_markdown.abstract_from_pmid.requests.get")
def test_invalid_xml(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "this is not xml <><>"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    md = get_abstract_markdown_from_pmid("55555555", email="test@test.com")
    assert md is None


@patch("pubmed_markdown.abstract_from_pmid.requests.get")
def test_empty_article_set(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<?xml version="1.0"?><PubmedArticleSet></PubmedArticleSet>'
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    md = get_abstract_markdown_from_pmid("66666666", email="test@test.com")
    assert md is None


def test_get_element_text_with_nested_tags():
    import xml.etree.ElementTree as ET

    el = ET.fromstring("<title>Normal and <i>italic</i> text</title>")
    assert _get_element_text(el) == "Normal and italic text"
