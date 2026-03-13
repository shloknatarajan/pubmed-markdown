"""Tests for HTML to Markdown conversion (PubMedHTMLToMarkdownConverter).

These are pure unit tests — no network calls, no mocking needed.
"""

import pytest
from pubmed_markdown.markdown_from_html import PubMedHTMLToMarkdownConverter


@pytest.fixture
def converter():
    return PubMedHTMLToMarkdownConverter()


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

MINIMAL_HTML = """
<html>
<head>
    <meta name="citation_title" content="Test Article Title">
    <meta name="citation_journal_title" content="Test Journal">
    <meta name="citation_doi" content="10.1234/test">
    <meta name="citation_pmid" content="12345678">
    <meta name="citation_author" content="Smith, John">
    <meta name="citation_author" content="Doe, Jane">
    <meta name="citation_publication_date" content="2024/01/15">
    <link rel="canonical" href="https://pmc.ncbi.nlm.nih.gov/articles/PMC9999999/">
</head>
<body></body>
</html>
"""


def test_metadata_extraction(converter):
    md = converter.convert_html(MINIMAL_HTML)
    assert "# Test Article Title" in md
    assert "Smith, John" in md
    assert "Doe, Jane" in md
    assert "Test Journal" in md
    assert "10.1234/test" in md
    assert "12345678" in md
    assert "PMC9999999" in md
    assert "2024/01/15" in md


def test_metadata_title_fallback(converter):
    html = "<html><head><title>Fallback Title - PMC</title></head><body></body></html>"
    md = converter.convert_html(html)
    assert "# Fallback Title" in md
    assert "- PMC" not in md


def test_metadata_doi_link(converter):
    md = converter.convert_html(MINIMAL_HTML)
    assert "[10.1234/test](https://doi.org/10.1234/test)" in md


def test_metadata_url(converter):
    md = converter.convert_html(MINIMAL_HTML)
    assert "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9999999/" in md


# ---------------------------------------------------------------------------
# Abstract extraction
# ---------------------------------------------------------------------------

SIMPLE_ABSTRACT_HTML = """
<html><head><title>Test</title></head><body>
<section class="abstract">
    <p>This is a simple abstract paragraph.</p>
    <p>Second paragraph of the abstract.</p>
</section>
</body></html>
"""

STRUCTURED_ABSTRACT_HTML = """
<html><head><title>Test</title></head><body>
<section class="abstract">
    <h3 class="pmc_sec_title">Background:</h3>
    <p>Background text here.</p>
    <h3 class="pmc_sec_title">Methods</h3>
    <p>Methods text here.</p>
    <h3 class="pmc_sec_title">Results</h3>
    <p>Results text here.</p>
</section>
</body></html>
"""


def test_simple_abstract(converter):
    md = converter.convert_html(SIMPLE_ABSTRACT_HTML)
    assert "## Abstract" in md
    assert "This is a simple abstract paragraph." in md
    assert "Second paragraph of the abstract." in md


def test_structured_abstract(converter):
    md = converter.convert_html(STRUCTURED_ABSTRACT_HTML)
    assert "## Abstract" in md
    assert "**Background:**" in md
    assert "Background text here." in md
    assert "**Methods:**" in md
    assert "Methods text here." in md
    assert "**Results:**" in md
    assert "Results text here." in md


def test_structured_abstract_strips_trailing_colon(converter):
    """Trailing colon in heading should not produce double colon like **Background::**"""
    md = converter.convert_html(STRUCTURED_ABSTRACT_HTML)
    assert "**Background::**" not in md


def test_no_abstract(converter):
    html = "<html><head><title>Test</title></head><body><p>No abstract here.</p></body></html>"
    md = converter.convert_html(html)
    assert "## Abstract" not in md


# ---------------------------------------------------------------------------
# Main content sections
# ---------------------------------------------------------------------------

SECTIONS_HTML = """
<html><head><title>Test</title></head><body>
<section class="main-article-body">
    <section id="sec1">
        <h2 class="pmc_sec_title">Introduction</h2>
        <p>Intro paragraph one.</p>
        <p>Intro paragraph two.</p>
    </section>
    <section id="sec2">
        <h2 class="pmc_sec_title">Methods</h2>
        <p>Methods paragraph.</p>
        <section id="sec2a">
            <h3 class="pmc_sec_title">Study Design</h3>
            <p>Study design details.</p>
        </section>
    </section>
</section>
</body></html>
"""


def test_main_content_sections(converter):
    md = converter.convert_html(SECTIONS_HTML)
    assert "## Introduction" in md
    assert "Intro paragraph one." in md
    assert "Intro paragraph two." in md
    assert "## Methods" in md
    assert "Methods paragraph." in md
    assert "### Study Design" in md
    assert "Study design details." in md


def test_abstract_section_skipped_in_main_content(converter):
    """Abstract sections inside main-article-body should not be duplicated."""
    html = """
    <html><head><title>Test</title></head><body>
    <section class="abstract"><p>Abstract text.</p></section>
    <section class="main-article-body">
        <section id="abs" class="abstract"><p>Abstract text.</p></section>
        <section id="sec1"><h2 class="pmc_sec_title">Intro</h2><p>Content.</p></section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    # Abstract should appear once (from _extract_abstract), not duplicated
    assert md.count("Abstract text.") == 1


def test_ref_list_section_skipped_in_main_content(converter):
    """ref-list sections inside main-article-body should be handled by _extract_references."""
    html = """
    <html><head><title>Test</title></head><body>
    <section class="main-article-body">
        <section id="sec1"><h2 class="pmc_sec_title">Discussion</h2><p>Discussion.</p></section>
        <section id="refs" class="ref-list"><p>Some ref.</p></section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    assert "## Discussion" in md


# ---------------------------------------------------------------------------
# Inline formatting
# ---------------------------------------------------------------------------

INLINE_HTML = """
<html><head><title>Test</title></head><body>
<section class="main-article-body">
    <section id="sec1">
        <h2 class="pmc_sec_title">Results</h2>
        <p>This has <em>italic</em> and <strong>bold</strong> and <sub>subscript</sub> and <sup>superscript</sup> text.</p>
        <p>Also <i>italic i</i> and <b>bold b</b> tags.</p>
        <p>Link: <a href="https://example.com">click here</a></p>
        <p>Internal ref: <a href="#fig1">Figure 1</a></p>
    </section>
</section>
</body></html>
"""


def test_inline_formatting(converter):
    md = converter.convert_html(INLINE_HTML)
    assert "*italic*" in md
    assert "**bold**" in md
    assert "_subscript_" in md
    assert "^superscript^" in md
    assert "*italic i*" in md
    assert "**bold b**" in md
    assert "[click here](https://example.com)" in md
    assert "[Figure 1](#fig1)" in md


# ---------------------------------------------------------------------------
# Table conversion
# ---------------------------------------------------------------------------

TABLE_HTML = """
<html><head><title>Test</title></head><body>
<section class="main-article-body">
    <section id="sec1">
        <section class="tw">
            <h3 class="obj_head">Table 1. Demographics</h3>
            <table>
                <thead>
                    <tr><th>Variable</th><th>Value</th></tr>
                </thead>
                <tbody>
                    <tr><td>Age</td><td>45.2</td></tr>
                    <tr><td>Sex</td><td>M/F</td></tr>
                </tbody>
            </table>
            <div class="caption">Patient demographics summary.</div>
        </section>
    </section>
</section>
</body></html>
"""


def test_table_conversion(converter):
    md = converter.convert_html(TABLE_HTML)
    assert "### Table 1. Demographics" in md
    assert "| Variable | Value |" in md
    assert "| --- | --- |" in md
    assert "| Age | 45.2 |" in md
    assert "| Sex | M/F |" in md
    assert "Table 1 Caption:" in md
    assert "Patient demographics summary." in md


def test_table_colspan(converter):
    html = """
    <html><head><title>Test</title></head><body>
    <section class="main-article-body">
        <section id="sec1">
            <table>
                <thead><tr><th colspan="2">Header Span</th><th>Col3</th></tr></thead>
                <tbody><tr><td>A</td><td>B</td><td>C</td></tr></tbody>
            </table>
        </section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    assert "Header Span" in md
    assert "Col3" in md
    assert "| A | B | C |" in md


def test_table_pipe_escaping(converter):
    html = """
    <html><head><title>Test</title></head><body>
    <section class="main-article-body">
        <section id="sec1">
            <table>
                <thead><tr><th>Ratio</th></tr></thead>
                <tbody><tr><td>A|B</td></tr></tbody>
            </table>
        </section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    assert "A\\|B" in md


def test_table_without_thead(converter):
    """Tables without <thead> should still produce valid markdown."""
    html = """
    <html><head><title>Test</title></head><body>
    <section class="main-article-body">
        <section id="sec1">
            <table>
                <tr><td>Name</td><td>Score</td></tr>
                <tr><td>Alice</td><td>95</td></tr>
            </table>
        </section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    assert "| Name | Score |" in md
    assert "| --- | --- |" in md
    assert "| Alice | 95 |" in md


def test_empty_table(converter):
    html = """
    <html><head><title>Test</title></head><body>
    <section class="main-article-body">
        <section id="sec1"><table></table></section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    # Should not crash — empty table produces no table markdown
    assert "| " not in md


# ---------------------------------------------------------------------------
# Figure processing
# ---------------------------------------------------------------------------

FIGURE_HTML = """
<html><head><title>Test</title></head><body>
<section class="main-article-body">
    <section id="sec1">
        <figure>
            <h3 class="obj_head">Figure 1. Study Flow</h3>
            <img src="/pmc/articles/PMC123/figure/fig1.jpg" alt="Study flow diagram">
            <figcaption>Flow diagram of study participants.</figcaption>
        </figure>
    </section>
</section>
</body></html>
"""


def test_figure_processing(converter):
    md = converter.convert_html(FIGURE_HTML)
    assert "### Figure 1. Study Flow" in md
    assert "![Study flow diagram]" in md
    assert "https://pmc.ncbi.nlm.nih.gov/pmc/articles/PMC123/figure/fig1.jpg" in md
    assert "Flow diagram of study participants." in md


def test_figure_relative_url_handling(converter):
    html = """
    <html><head><title>Test</title></head><body>
    <section class="main-article-body">
        <section id="sec1">
            <figure><img src="//cdn.example.com/img.png" alt="CDN image"></figure>
        </section>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    assert "https://cdn.example.com/img.png" in md


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

REFERENCES_HTML = """
<html><head><title>Test</title></head><body>
<section class="ref-list">
    <ul class="ref-list">
        <li>
            <cite>Smith J et al. Some Paper. J Med. 2020;1:1-5.</cite>
            <a href="https://doi.org/10.1234/ref1">DOI</a>
            <a href="https://pubmed.ncbi.nlm.nih.gov/111">PubMed</a>
        </li>
        <li>
            <cite>Doe J. Another Paper. Nature. 2021;2:10-15.</cite>
            <a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC222">PMC</a>
        </li>
    </ul>
</section>
</body></html>
"""


def test_references_extraction(converter):
    md = converter.convert_html(REFERENCES_HTML)
    assert "## References" in md
    assert "1." in md
    assert "Smith J et al." in md
    assert "[DOI](https://doi.org/10.1234/ref1)" in md
    assert "[PubMed](https://pubmed.ncbi.nlm.nih.gov/111)" in md
    assert "2." in md
    assert "Doe J." in md
    assert "[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC222)" in md


def test_references_without_cite_tag(converter):
    html = """
    <html><head><title>Test</title></head><body>
    <section class="ref-list">
        <ul class="ref-list">
            <li>Raw reference text without cite tag.</li>
        </ul>
    </section>
    </body></html>
    """
    md = converter.convert_html(html)
    assert "## References" in md
    assert "Raw reference text without cite tag." in md


def test_no_references(converter):
    html = "<html><head><title>Test</title></head><body><p>No refs.</p></body></html>"
    md = converter.convert_html(html)
    assert "## References" not in md


# ---------------------------------------------------------------------------
# Scanned document handling
# ---------------------------------------------------------------------------

SCANNED_HTML = """
<html><head>
    <title>Old Paper</title>
    <meta name="ncbi_type" content="scanpage">
</head><body>
<section class="abstract"><p>Scanned abstract text.</p></section>
<section class="scanned-pages">
    <figure class="fig-scanned"><img src="/scan/page1.png" alt="Page 1"></figure>
    <figure class="fig-scanned"><img src="/scan/page2.png" alt="Page 2"></figure>
</section>
</body></html>
"""


def test_scanned_document_detection(converter):
    md = converter.convert_html(SCANNED_HTML)
    assert "scanned document" in md.lower()
    assert "## Abstract" in md
    assert "Scanned abstract text." in md
    assert "## Full Text (Scanned Pages)" in md
    assert "### Page 1" in md
    assert "### Page 2" in md


def test_non_scanned_document(converter):
    html = "<html><head><title>Normal</title></head><body><p>Normal article.</p></body></html>"
    md = converter.convert_html(html)
    assert "scanned document" not in md.lower()


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------


def test_clean_text_html_entities(converter):
    assert converter._clean_text("foo &amp; bar") == "foo & bar"
    assert converter._clean_text("a &lt; b &gt; c") == "a < b > c"


def test_clean_text_whitespace(converter):
    assert converter._clean_text("  lots   of    spaces  ") == "lots of spaces"
    assert converter._clean_text("line\n\nbreak") == "line break"


def test_clean_text_empty(converter):
    assert converter._clean_text("") == ""
    assert converter._clean_text(None) == ""


def test_clean_markdown_trailing_newlines(converter):
    result = converter._clean_markdown("Hello\n\n\n\n\nWorld\n\n\n")
    assert result == "Hello\n\nWorld\n"


# ---------------------------------------------------------------------------
# convert_file
# ---------------------------------------------------------------------------


def test_convert_file(converter, tmp_path):
    html_file = tmp_path / "test.html"
    html_file.write_text(MINIMAL_HTML)
    md = converter.convert_file(str(html_file))
    assert "# Test Article Title" in md


# ---------------------------------------------------------------------------
# Full pipeline: end-to-end HTML → Markdown
# ---------------------------------------------------------------------------

FULL_ARTICLE_HTML = """
<html>
<head>
    <meta name="citation_title" content="Pharmacogenomics of CYP2D6">
    <meta name="citation_journal_title" content="Clinical Pharmacology">
    <meta name="citation_doi" content="10.1000/cphar.2024">
    <meta name="citation_pmid" content="99887766">
    <meta name="citation_author" content="Garcia, Maria">
    <meta name="citation_publication_date" content="2024/06/01">
    <link rel="canonical" href="https://pmc.ncbi.nlm.nih.gov/articles/PMC1111111/">
</head>
<body>
<section class="abstract">
    <h3 class="pmc_sec_title">Objective</h3>
    <p>To study CYP2D6 variants.</p>
    <h3 class="pmc_sec_title">Methods</h3>
    <p>We performed genotyping on 500 patients.</p>
</section>
<section class="main-article-body">
    <section id="intro">
        <h2 class="pmc_sec_title">Introduction</h2>
        <p>CYP2D6 is a key enzyme in drug metabolism.</p>
    </section>
    <section id="methods">
        <h2 class="pmc_sec_title">Methods</h2>
        <p>DNA was extracted from blood samples.</p>
        <section class="tw">
            <h3 class="obj_head">Table 1. Genotype Frequencies</h3>
            <table>
                <thead><tr><th>Genotype</th><th>Frequency</th></tr></thead>
                <tbody>
                    <tr><td>*1/*1</td><td>0.45</td></tr>
                    <tr><td>*1/*4</td><td>0.25</td></tr>
                </tbody>
            </table>
        </section>
    </section>
    <section id="results">
        <h2 class="pmc_sec_title">Results</h2>
        <p>We found significant associations (p &lt; 0.001).</p>
        <figure>
            <h3 class="obj_head">Figure 1. Allele Distribution</h3>
            <img src="/pmc/articles/PMC1111111/fig1.png" alt="Allele distribution chart">
            <figcaption>Distribution of CYP2D6 alleles across populations.</figcaption>
        </figure>
    </section>
</section>
<section class="ref-list">
    <ul class="ref-list">
        <li>
            <cite>Gaedigk A et al. PharmVar. Clin Pharmacol Ther. 2018;103:399.</cite>
            <a href="https://doi.org/10.1002/cpt.957">DOI</a>
        </li>
    </ul>
</section>
</body>
</html>
"""


def test_full_article_conversion(converter):
    md = converter.convert_html(FULL_ARTICLE_HTML)

    # Metadata
    assert "# Pharmacogenomics of CYP2D6" in md
    assert "Garcia, Maria" in md
    assert "Clinical Pharmacology" in md
    assert "PMC1111111" in md

    # Abstract
    assert "## Abstract" in md
    assert "**Objective:**" in md
    assert "CYP2D6 variants" in md

    # Sections
    assert "## Introduction" in md
    assert "CYP2D6 is a key enzyme" in md
    assert "## Methods" in md
    assert "## Results" in md

    # HTML entities decoded
    assert "p < 0.001" in md

    # Table
    assert "### Table 1. Genotype Frequencies" in md
    assert "| Genotype | Frequency |" in md
    assert "| *1/*1 | 0.45 |" in md

    # Figure
    assert "### Figure 1. Allele Distribution" in md
    assert "![Allele distribution chart]" in md
    assert "Distribution of CYP2D6 alleles" in md

    # References
    assert "## References" in md
    assert "Gaedigk A et al." in md
    assert "[DOI](https://doi.org/10.1002/cpt.957)" in md

    # Document ends with single newline
    assert md.endswith("\n")
    assert not md.endswith("\n\n")
