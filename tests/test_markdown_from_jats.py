"""Tests for JATS XML to Markdown conversion (JATSToMarkdownConverter)."""

import pytest

from pubmed_markdown.manage_records import parse_markdown_metadata
from pubmed_markdown.markdown_from_jats import JATSToMarkdownConverter


@pytest.fixture
def converter():
    return JATSToMarkdownConverter()


FULL_JATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<pmc-articleset>
  <article xmlns:xlink="http://www.w3.org/1999/xlink">
    <front>
      <journal-meta>
        <journal-title-group>
          <journal-title>Clinical Pharmacology &amp; Therapeutics</journal-title>
        </journal-title-group>
      </journal-meta>
      <article-meta>
        <article-id pub-id-type="pmid">99887766</article-id>
        <article-id pub-id-type="pmc">1111111</article-id>
        <article-id pub-id-type="doi">10.1000/cphar.2024</article-id>
        <title-group>
          <article-title>Pharmacogenomics of <italic>CYP2D6</italic>
            in Clinical Practice</article-title>
        </title-group>
        <contrib-group>
          <contrib contrib-type="author">
            <name><surname>Garcia</surname><given-names>Maria</given-names></name>
          </contrib>
          <contrib contrib-type="author">
            <collab>CPIC Consortium</collab>
          </contrib>
        </contrib-group>
        <pub-date pub-type="epub">
          <day>5</day><month>6</month><year>2024</year>
        </pub-date>
        <abstract abstract-type="graphical">
          <p>Graphical abstract caption should be skipped.</p>
        </abstract>
        <abstract>
          <sec>
            <title>Objective:</title>
            <p>To study <italic>CYP2D6</italic> variants.</p>
          </sec>
          <sec>
            <title>Results</title>
            <p>Significant effect (<italic>p</italic> &lt; 0.001).</p>
          </sec>
        </abstract>
      </article-meta>
    </front>
    <body>
      <sec id="s1">
        <title>Introduction</title>
        <p><bold>CYP2D6</bold> metabolizes H<sub>2</sub>O and 10<sup>3</sup> substrates <xref ref-type="bibr" rid="r1">1</xref>.</p>
        <p>See <ext-link xlink:href="https://pharmvar.org">PharmVar</ext-link> for definitions.</p>
        <sec id="s1a">
          <title>Background Details</title>
          <p>Nested subsection text.</p>
          <list list-type="bullet">
            <list-item><p>First bullet</p></list-item>
            <list-item><p>Second bullet</p></list-item>
          </list>
        </sec>
      </sec>
      <sec id="s2">
        <title>Results</title>
        <p>Summary of genotypes:<table-wrap id="t1">
          <label>Table 1</label>
          <caption><p>Genotype Frequencies</p></caption>
          <table>
            <thead>
              <tr><th colspan="2">Genotype | Group</th><th>Frequency</th></tr>
            </thead>
            <tbody>
              <tr><td>*1/*1</td><td>Normal</td><td>0.45</td></tr>
              <tr><td>*1/*4</td><td>Intermediate</td><td>0.25</td></tr>
            </tbody>
          </table>
          <table-wrap-foot><p>Data from 500 patients.</p></table-wrap-foot>
        </table-wrap>After table text.</p>
      </sec>
    </body>
    <floats-group>
      <fig id="f1">
        <label>Figure 1</label>
        <caption><p>Allele distribution across cohorts.</p></caption>
        <graphic xlink:href="cphar-1111-f001"/>
      </fig>
    </floats-group>
    <back>
      <ref-list>
        <ref id="r1">
          <element-citation>
            <person-group>
              <name><surname>Gaedigk</surname><given-names>A</given-names></name>
              <etal/>
            </person-group>
            <article-title>PharmVar</article-title>
            <source>Clin Pharmacol Ther</source>
            <year>2018</year>
            <volume>103</volume>
            <fpage>399</fpage>
            <lpage>406</lpage>
            <pub-id pub-id-type="doi">10.1002/cpt.957</pub-id>
            <pub-id pub-id-type="pmid">29134625</pub-id>
            <pub-id pub-id-type="pmc">5869103</pub-id>
          </element-citation>
        </ref>
        <ref id="r2">
          <mixed-citation>Unstructured citation text 2023.</mixed-citation>
        </ref>
      </ref-list>
    </back>
  </article>
</pmc-articleset>
"""


def test_full_jats_conversion(converter):
    md = converter.convert_xml(FULL_JATS_XML)

    # Metadata
    assert "# Pharmacogenomics of *CYP2D6* in Clinical Practice" in md
    assert "**Authors:** Maria Garcia, CPIC Consortium" in md
    assert "**Journal:** Clinical Pharmacology & Therapeutics" in md
    assert "**Date:** 2024/06/05" in md
    assert "**DOI:** [10.1000/cphar.2024](https://doi.org/10.1000/cphar.2024)" in md
    assert "**PMID:** 99887766" in md
    assert "**PMCID:** PMC1111111" in md
    assert "**URL:** https://pmc.ncbi.nlm.nih.gov/articles/PMC1111111/" in md

    # Compatible with manage_records.parse_markdown_metadata
    parsed_meta = parse_markdown_metadata(md)
    assert parsed_meta["pmid"] == "99887766"
    assert parsed_meta["pmcid"] == "PMC1111111"
    assert parsed_meta["url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC1111111/"

    # Main abstract chosen over graphical abstract
    assert "## Abstract" in md
    assert "**Objective:**" in md
    assert "**Objective::**" not in md
    assert "Graphical abstract caption" not in md
    assert "*p* < 0.001" in md

    # Sections, inline formatting, lists
    assert "## Introduction" in md
    assert "**CYP2D6** metabolizes H_2_O and 10^3^ substrates [1]." in md
    assert "[PharmVar](https://pharmvar.org)" in md
    assert "### Background Details" in md
    assert "- First bullet" in md
    assert "- Second bullet" in md

    # Table nested inside <p> extracted cleanly
    assert "Summary of genotypes:" in md
    assert "### Table 1" in md
    assert "| Genotype \\| Group |  | Frequency |" in md
    assert "| *1/*1 | Normal | 0.45 |" in md
    assert "*Data from 500 patients.*" in md
    assert "After table text." in md

    # Floats group figure
    assert "### Figure 1" in md
    assert "Allele distribution across cohorts." in md
    assert (
        "![Figure 1](https://pmc.ncbi.nlm.nih.gov/articles/instance/cphar-1111-f001/bin/cphar-1111-f001.jpg)"
        in md
    )

    # References (structured + unstructured mixed-citation fallback, no double periods)
    assert "## References" in md
    assert (
        "1. Gaedigk A et al. PharmVar. *Clin Pharmacol Ther*. **103** (2018). 399-406."
        in md
    )
    assert "et al.." not in md
    assert "[DOI](https://doi.org/10.1002/cpt.957)" in md
    assert "[PubMed](https://pubmed.ncbi.nlm.nih.gov/29134625)" in md
    assert "[PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5869103/)" in md
    assert "2. Unstructured citation text 2023." in md

    assert md.endswith("\n")
    assert not md.endswith("\n\n")


def test_direct_paragraphs_in_body_without_sec(converter):
    """Short articles/letters often put <p> directly under <body> without <sec>."""
    xml = """<article>
      <front><article-meta><title-group><article-title>Letter</article-title></title-group></article-meta></front>
      <body>
        <p>Direct paragraph one.</p>
        <p>Direct paragraph two.</p>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "# Letter" in md
    assert "Direct paragraph one." in md
    assert "Direct paragraph two." in md


def test_simple_abstract_and_ordered_list(converter):
    xml = """<article>
      <front><article-meta>
        <title-group><article-title>Simple</article-title></title-group>
        <abstract><p>Simple abstract text.</p></abstract>
      </article-meta></front>
      <body>
        <sec><title>Steps</title>
          <list list-type="order">
            <list-item><p>Step one</p></list-item>
            <list-item><p>Step two</p></list-item>
          </list>
        </sec>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "Simple abstract text." in md
    assert "1. Step one" in md
    assert "2. Step two" in md


def test_invalid_colspan_handled_safely(converter):
    xml = """<article>
      <body>
        <table-wrap>
          <table>
            <thead><tr><th colspan="">A</th><th>B</th></tr></thead>
            <tbody><tr><td colspan="bad">1</td><td>2</td></tr></tbody>
          </table>
        </table-wrap>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "| A | B |" in md
    assert "| 1 | 2 |" in md


def test_no_article_element_returns_empty(converter):
    assert converter.convert_xml("<pmc-articleset></pmc-articleset>") == ""


def test_convert_file(converter, tmp_path):
    xml_file = tmp_path / "PMC1111111.xml"
    xml_file.write_text(FULL_JATS_XML, encoding="utf-8")
    md = converter.convert_file(str(xml_file))
    assert "# Pharmacogenomics of *CYP2D6* in Clinical Practice" in md


def test_back_matter_extraction(converter):
    xml = """<article>
      <front><article-meta><title-group><article-title>Back Matter Test</article-title></title-group></article-meta></front>
      <body><sec><title>Intro</title><p>Body text.</p></sec></body>
      <back>
        <ack><p>We thank the clinic staff.</p></ack>
        <sec sec-type="data-availability">
          <title>Data Availability Statement</title>
          <p>Data available upon request.</p>
        </sec>
        <notes notes-type="COI-statement">
          <title>Conflicts of Interest</title>
          <p>The authors declare no conflicts.</p>
        </notes>
        <glossary>
          <title>Abbreviations:</title>
          <def-list>
            <def-item><term>DILI</term><def><p>Drug-induced liver injury</p></def></def-item>
            <def-item><term>GWAS</term><def><p>Genome-wide association study</p></def></def-item>
          </def-list>
        </glossary>
        <glossary>
          <title>Additional Abbreviations</title>
          <p>Used below: <array><tbody><tr><td>ALT</td><td>Alanine aminotransferase</td></tr></tbody></array></p>
        </glossary>
        <app-group>
          <app>
            <title>Appendix A</title>
            <p>Supplementary derivation.</p>
          </app>
        </app-group>
        <fn-group>
          <fn><p><bold>Disclosures:</bold> None.</p></fn>
        </fn-group>
      </back>
    </article>"""
    md = converter.convert_xml(xml)
    assert "## Acknowledgments" in md
    assert "We thank the clinic staff." in md
    assert "## Data Availability Statement" in md
    assert "Data available upon request." in md
    assert "## Conflicts of Interest" in md
    assert "The authors declare no conflicts." in md
    assert "## Abbreviations" in md
    assert "- **DILI:** Drug-induced liver injury" in md
    assert "- **GWAS:** Genome-wide association study" in md
    assert "| ALT | Alanine aminotransferase |" in md
    assert "## Appendix A" in md
    assert "Supplementary derivation." in md
    assert "## Notes" in md
    assert "**Disclosures:** None." in md


def test_formatting_quirk_fixes(converter):
    """Covers .jpg.jpg URLs, double bullets, double periods in refs, and [[1]] citations."""
    xml = """<article xmlns:xlink="http://www.w3.org/1999/xlink">
      <body>
        <sec>
          <title>Highlights</title>
          <list list-type="bullet">
            <list-item><p>- First highlight with leading dash.</p></list-item>
            <list-item><p>• Second highlight with unicode bullet.</p></list-item>
          </list>
          <p>Already bracketed [<xref ref-type="bibr">1</xref>] and multi [<xref ref-type="bibr">2</xref>,<xref ref-type="bibr">3</xref>].</p>
          <fig>
            <label>Figure 1</label>
            <graphic xlink:href="nihms-1855942-f0002.jpg"/>
          </fig>
        </sec>
      </body>
      <back>
        <ref-list>
          <ref>
            <element-citation>
              <person-group>
                <name><surname>Teo</surname><given-names>K.K.</given-names></name>
                <name><surname>Rafiq</surname><given-names>T.</given-names></name>
              </person-group>
              <article-title>Risk Factors</article-title>
              <source>Can. J. Cardiol.</source>
              <volume>37</volume>
              <year>2021</year>
              <pub-id pub-id-type="doi">10.1016/j.cjca.2021.02.009</pub-id>
            </element-citation>
          </ref>
        </ref-list>
      </back>
    </article>"""
    md = converter.convert_xml(xml)
    assert "- First highlight with leading dash." in md
    assert "- - " not in md
    assert "- Second highlight with unicode bullet." in md
    assert "Already bracketed [1] and multi [2,3]." in md
    assert "[[" not in md
    assert (
        "![Figure 1](https://pmc.ncbi.nlm.nih.gov/articles/instance/nihms-1855942-f0002/bin/nihms-1855942-f0002.jpg)"
        in md
    )
    assert ".jpg.jpg" not in md
    assert "1. Teo K.K., Rafiq T. Risk Factors. *Can. J. Cardiol.* **37** (2021)." in md
    assert ".." not in md
