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


def test_table_rowspan_multirow_thead_and_break_spacing(converter):
    """rowspan > 1, multi-row thead merging, and <break/> cell spacing."""
    xml = """<article>
      <body>
        <table-wrap>
          <label>Table 1</label>
          <table>
            <thead>
              <tr>
                <th rowspan="2">Characteristic</th>
                <th colspan="2">No. of patients (%)</th>
                <th rowspan="2">Toxicity risk<break/>OR (± 95% CI)</th>
              </tr>
              <tr>
                <th>Ex-case (n=144)</th>
                <th>Ex-control (n=144)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td rowspan="2">ANEMIA<break/>grade 1-2</td>
                <td>21 (7.9)</td>
                <td>--</td>
                <td>1.00 (ref)</td>
              </tr>
              <tr>
                <td>87 (32.8)</td>
                <td>3 (11.5)</td>
                <td>1.61 (0.37-6.94)</td>
              </tr>
            </tbody>
          </table>
        </table-wrap>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert (
        "| Characteristic | No. of patients (%) - Ex-case (n=144) "
        "| No. of patients (%) - Ex-control (n=144) | Toxicity risk OR (± 95% CI) |"
        in md
    )
    assert "| ANEMIA grade 1-2 | 21 (7.9) | -- | 1.00 (ref) |" in md
    # Row 2 must stay aligned under cols 1-3 with empty col 0 (not shifted left)
    assert "|  | 87 (32.8) | 3 (11.5) | 1.61 (0.37-6.94) |" in md


def test_table_cell_breaks_preserve_inline_sub_sup(converter):
    """<break/> and <p> insert spaces, while <sub>/<sup>/<italic> stay contiguous."""
    xml = """<article>
      <body>
        <table-wrap>
          <table>
            <thead><tr><th>Formula</th><th>Gene</th></tr></thead>
            <tbody>
              <tr>
                <td>H<sub>2</sub>O<break/>10<sup>3</sup></td>
                <td><p><italic>ERCC1</italic> p.Asn118=</p><p>rs11615</p></td>
              </tr>
            </tbody>
          </table>
        </table-wrap>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "| H2O 103 | ERCC1 p.Asn118= rs11615 |" in md


def test_boxed_text_extraction(converter):
    """<boxed-text> under <body> (wrapping <sec>) and with <label>/<caption>."""
    xml = """<article>
      <body>
        <boxed-text>
          <sec>
            <title>What is already known about this subject</title>
            <p><list list-type="bullet">
              <list-item><p>Point one.</p></list-item>
            </list></p>
          </sec>
          <sec>
            <title>What this study adds</title>
            <p><list list-type="bullet">
              <list-item><p>Point two.</p></list-item>
            </list></p>
          </sec>
        </boxed-text>
        <sec>
          <title>Discussion</title>
          <p>Main text.</p>
          <boxed-text>
            <label>Box 1</label>
            <caption><title>Key Takeaways</title></caption>
            <p>Takeaway details.</p>
          </boxed-text>
        </sec>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "## What is already known about this subject" in md
    assert "- Point one." in md
    assert "## What this study adds" in md
    assert "- Point two." in md
    assert "### Box 1: Key Takeaways" in md
    assert "Takeaway details." in md


def test_supplementary_material_and_empty_section_suppression(converter):
    """<supplementary-material> renders captions/files; truly empty <sec> is omitted."""
    xml = """<article xmlns:xlink="http://www.w3.org/1999/xlink">
      <body>
        <sec>
          <title>Supporting information</title>
          <supplementary-material id="s1">
            <caption><p><bold>TABLE S1.</bold> Results after imputation</p></caption>
            <media xlink:href="BCP-91-297-s002.zip">
              <caption><p>Click here for additional data file.</p></caption>
            </media>
          </supplementary-material>
          <supplementary-material id="s2">
            <label>1</label>
            <media xlink:href="supplement-1.pdf"/>
          </supplementary-material>
        </sec>
        <sec>
          <title>Completely Empty Section</title>
        </sec>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "## Supporting information" in md
    assert "- **TABLE S1.** Results after imputation (BCP-91-297-s002.zip)" in md
    assert "Click here for additional data file." not in md
    assert "- supplement-1.pdf" in md
    assert "Completely Empty Section" not in md


def test_nested_notes_declarations(converter):
    """Springer Nature / BMC nest <notes> inside <notes><title>Declarations</title>."""
    xml = """<article>
      <body><sec><title>Intro</title><p>Body text.</p></sec></body>
      <back>
        <notes>
          <title>Declarations</title>
          <notes id="n1">
            <title>Ethics approval</title>
            <p>Approved by IRB.</p>
          </notes>
          <notes id="n2">
            <title>Competing interests</title>
            <p>The authors declare no competing interests.</p>
          </notes>
        </notes>
      </back>
    </article>"""
    md = converter.convert_xml(xml)
    assert "## Declarations" in md
    assert "### Ethics approval" in md
    assert "Approved by IRB." in md
    assert "### Competing interests" in md
    assert "The authors declare no competing interests." in md


def test_front_funding_statement_fallback_and_dedup(converter):
    """<front><funding-group><funding-statement> renders when <back> lacks funding, without duplicating."""
    xml_front_only = """<article xmlns:xlink="http://www.w3.org/1999/xlink">
      <front>
        <article-meta>
          <title-group><article-title>Funded Study</article-title></title-group>
          <funding-group>
            <funding-statement>Supported by grant NIH-123 (<ext-link xlink:href="https://nih.gov">NIH</ext-link>).</funding-statement>
          </funding-group>
        </article-meta>
      </front>
      <body><p>Body text.</p></body>
    </article>"""
    md_front = converter.convert_xml(xml_front_only)
    assert "## Funding" in md_front
    assert "Supported by grant NIH-123 ([NIH](https://nih.gov))." in md_front

    xml_both = """<article>
      <front>
        <article-meta>
          <funding-group>
            <funding-statement>Front funding text.</funding-statement>
          </funding-group>
        </article-meta>
      </front>
      <body><p>Body text.</p></body>
      <back>
        <notes notes-type="funding-information">
          <title>Funding</title>
          <p>Back funding text.</p>
        </notes>
      </back>
    </article>"""
    md_both = converter.convert_xml(xml_both)
    assert md_both.count("## Funding") == 1
    assert "Back funding text." in md_both
    assert "Front funding text." not in md_both


def test_mathml_formulas_and_alternatives(converter):
    """Presentation MathML preserves fractions, scripts, roots, labels, and avoids <alternatives> dupes."""
    xml = """<article xmlns:mml="http://www.w3.org/1998/Math/MathML">
      <body>
        <sec>
          <title>Methods</title>
          <p>Heritability <mml:math display="inline"><mml:msubsup><mml:mi>h</mml:mi><mml:mi>SNP</mml:mi><mml:mn>2</mml:mn></mml:msubsup></mml:math> was estimated.</p>
          <disp-formula>
            <label>(1)</label>
            <alternatives>
              <tex-math>E = \\frac{a}{b}</tex-math>
              <mml:math display="block">
                <mml:mrow>
                  <mml:mi>E</mml:mi><mml:mo>=</mml:mo>
                  <mml:mfrac>
                    <mml:mrow><mml:msub><mml:mi>fu</mml:mi><mml:mi>b</mml:mi></mml:msub><mml:mo>×</mml:mo><mml:msub><mml:mi>CL</mml:mi><mml:mi>int</mml:mi></mml:msub></mml:mrow>
                    <mml:mrow><mml:msub><mml:mi>Q</mml:mi><mml:mi>liver</mml:mi></mml:msub><mml:mo>+</mml:mo><mml:msub><mml:mi>fu</mml:mi><mml:mi>b</mml:mi></mml:msub></mml:mrow>
                  </mml:mfrac>
                </mml:mrow>
              </mml:math>
            </alternatives>
          </disp-formula>
          <disp-formula>
            <label>(2)</label>
            <mml:math display="block">
              <mml:mrow>
                <mml:mi>Fold</mml:mi><mml:mi>error</mml:mi><mml:mo>=</mml:mo>
                <mml:mfrac>
                  <mml:mrow><mml:mi>Predicted</mml:mi><mml:mi>value</mml:mi></mml:mrow>
                  <mml:mrow><mml:mi>Observed</mml:mi><mml:mi>value</mml:mi></mml:mrow>
                </mml:mfrac>
              </mml:mrow>
            </mml:math>
          </disp-formula>
          <p>Root: <mml:math><mml:msqrt><mml:mi>x</mml:mi></mml:msqrt></mml:math> and <mml:math><mml:mi>D</mml:mi><mml:mi>o</mml:mi><mml:mi>s</mml:mi><mml:mi>e</mml:mi></mml:math>.</p>
        </sec>
      </body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "Heritability h_SNP_^2^ was estimated." in md
    assert "E = (fu_b_ × CL_int_) / (Q_liver_ + fu_b_) (1)" in md
    assert "\\frac" not in md
    assert "Fold error = (Predicted value) / (Observed value) (2)" in md
    assert "Root: √(x) and Dose." in md


def test_secondary_abstracts_key_points_and_author_summary(converter):
    """Substantive secondary abstracts (key-points, summary) are extracted; teaser/web-summary skipped."""
    xml = """<article>
      <front>
        <article-meta>
          <title-group><article-title>Study</article-title></title-group>
          <abstract abstract-type="key-points">
            <title>Key Points</title>
            <sec><title>Question</title><p>Does CYP2C19 affect drug levels?</p></sec>
            <sec><title>Findings</title><p>Yes, significantly.</p></sec>
          </abstract>
          <abstract abstract-type="teaser">
            <p>Teaser text should be skipped.</p>
          </abstract>
          <abstract abstract-type="web-summary">
            <p>Web summary should be skipped.</p>
          </abstract>
          <abstract>
            <p>Primary abstract body.</p>
          </abstract>
          <abstract abstract-type="summary">
            <title>Author Summary</title>
            <p>Plain language author summary.</p>
          </abstract>
        </article-meta>
      </front>
      <body><p>Body.</p></body>
    </article>"""
    md = converter.convert_xml(xml)
    assert "## Abstract\n\nPrimary abstract body." in md
    assert "## Key Points" in md
    assert "**Question:**" in md
    assert "Does CYP2C19 affect drug levels?" in md
    assert "## Author Summary" in md
    assert "Plain language author summary." in md
    assert "Teaser text should be skipped." not in md
    assert "Web summary should be skipped." not in md


def test_fn_group_inside_section_and_disp_quote(converter):
    """PeerJ-style <fn-group> inside <sec> and <disp-quote> blockquotes."""
    xml = """<article>
      <body>
        <sec>
          <title>Results</title>
          <p>Participant statement:</p>
          <disp-quote>
            <p>First quoted paragraph.</p>
            <p>Second quoted paragraph.</p>
            <attrib>Participant 12</attrib>
          </disp-quote>
        </sec>
      </body>
      <back>
        <sec sec-type="additional-information">
          <title>Additional Information and Declarations</title>
          <fn-group content-type="competing-interests">
            <title>Competing Interests</title>
            <fn><p>The authors declare no competing interests.</p></fn>
          </fn-group>
          <fn-group content-type="author-contributions">
            <title>Author Contributions</title>
            <fn><p>Jane Doe conceived the study.</p></fn>
          </fn-group>
        </sec>
      </back>
    </article>"""
    md = converter.convert_xml(xml)
    assert "> First quoted paragraph." in md
    assert "> Second quoted paragraph." in md
    assert "> — Participant 12" in md
    assert "## Additional Information and Declarations" in md
    assert "### Competing Interests" in md
    assert "The authors declare no competing interests." in md
    assert "### Author Contributions" in md
    assert "Jane Doe conceived the study." in md


def test_title_footnote_stripping_and_string_name_references(converter):
    """Strip <sup><xref ref-type='fn'> from titles; extract <string-name>/<collab>/<elocation-id> in refs."""
    xml = """<article>
      <front>
        <article-meta>
          <title-group>
            <article-title>HLA-DRB1 in 10<sup>3</sup> patients<sup><xref ref-type="fn" rid="fn1">☆</xref></sup></article-title>
          </title-group>
          <contrib-group>
            <contrib contrib-type="author">
              <string-name><given-names>Alice</given-names> <surname>Smith</surname></string-name>
            </contrib>
          </contrib-group>
        </article-meta>
      </front>
      <body><p>Body text.</p></body>
      <back>
        <ref-list>
          <ref id="r1">
            <mixed-citation>
              <person-group>
                <string-name><surname>Baigent</surname> <given-names>C</given-names></string-name>,
                <string-name><surname>Keech</surname> <given-names>A</given-names></string-name>,
                <etal>et al</etal>
              </person-group>.
              <article-title>Cholesterol roadmap</article-title>.
              <source>Glob Heart</source>
              <year>2022</year>;<volume>17</volume>:<elocation-id>75</elocation-id>.
              <pub-id pub-id-type="doi">10.5334/gh.1154</pub-id>
            </mixed-citation>
          </ref>
          <ref id="r2">
            <element-citation>
              <collab>WHO Working Group</collab>
              <article-title>Global guidelines</article-title>
              <source>WHO</source>
              <year>2023</year>
            </element-citation>
          </ref>
        </ref-list>
      </back>
    </article>"""
    md = converter.convert_xml(xml)
    assert "# HLA-DRB1 in 10^3^ patients\n" in md
    assert "☆" not in md
    assert "**Authors:** Alice Smith" in md
    assert (
        "1. Baigent C, Keech A et al. Cholesterol roadmap. *Glob Heart*. **17** (2022). 75."
        in md
    )
    assert "2. WHO Working Group. Global guidelines. *WHO*. (2023)" in md
