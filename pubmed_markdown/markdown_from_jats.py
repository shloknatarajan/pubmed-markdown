"""
JATS XML to Markdown Converter

Converts JATS/NLM XML (as returned by NCBI E-utilities efetch and Europe PMC
fullTextXML) to structured markdown matching PubMedHTMLToMarkdownConverter's
schema.
"""

import html
import re
from typing import Any, Dict

from bs4 import BeautifulSoup, NavigableString, Tag
from loguru import logger

from .table_utils import convert_table_to_markdown

# Block-level JATS elements that can appear inside <p> but should be
# extracted and rendered separately (not as inline text).
_BLOCK_ELEMENTS = {
    "table-wrap",
    "fig",
    "disp-formula",
    "disp-quote",
    "list",
    "array",
    "def-list",
    "boxed-text",
    "supplementary-material",
}
_IGNORED_ABSTRACT_TYPES = {"graphical", "toc", "teaser", "web-summary"}
_SECONDARY_ABSTRACT_TITLES = {
    "key-points": "Key Points",
    "summary": "Summary",
    "executive-summary": "Executive Summary",
    "plain-language-summary": "Plain Language Summary",
}


def _is_inside_square_brackets(tag: Tag) -> bool:
    """Return True if an inline <xref> is already enclosed by literal '[' in its parent."""
    sep_re = re.compile(r"^[\s,;:\-–—]*$")
    sib = tag.previous_sibling
    while sib is not None:
        if isinstance(sib, NavigableString):
            s = str(sib)
            if sep_re.match(s):
                sib = sib.previous_sibling
                continue
            return s.rstrip().endswith("[")
        if isinstance(sib, Tag) and sib.name == "xref":
            sib = sib.previous_sibling
            continue
        return False
    return False


def _join_citation_parts(parts: list[str]) -> str:
    """Join citation segments with '. ' without creating double periods."""
    result = ""
    for part in parts:
        if not part:
            continue
        if not result:
            result = part
        elif result.endswith((".", "?", "!")) or result.endswith((".*", "?*", "!*")):
            result += f" {part}"
        else:
            result += f". {part}"
    return result


_MATHML_SPACED_OPS = {
    "=",
    "+",
    "-",
    "−",
    "×",
    "·",
    "±",
    "∓",
    "<",
    ">",
    "≤",
    "≥",
    "≈",
    "≠",
    "∼",
    "≡",
    "∝",
    "→",
    "←",
    "↔",
    "⇒",
    "⇔",
}
_MATHML_FRAC_OPS_RE = re.compile(r"[+\-−×·/=±≤≥<>]|\s")


def _wrap_if_compound(expr: str) -> str:
    """Wrap a MathML numerator/denominator in parens if it contains operators or spaces."""
    s = expr.strip()
    if not s:
        return s
    if s.startswith("(") and s.endswith(")"):
        depth = 0
        balanced = True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i < len(s) - 1:
                    balanced = False
                    break
        if balanced and depth == 0:
            return s
    if _MATHML_FRAC_OPS_RE.search(s):
        return f"({s})"
    return s


def _starts_with_word(text: str) -> bool:
    s = text.lstrip()
    return len(s) >= 2 and s[0].isalpha() and s[1].isalpha()


def _ends_with_word(text: str) -> bool:
    s = text.rstrip()
    return len(s) >= 2 and s[-1].isalpha() and s[-2].isalpha()


def _mathml_to_text(node: Tag) -> str:
    """Convert a Presentation MathML subtree into readable inline text."""
    name = (node.name or "").lower()

    if name in ("mi", "mn", "mtext", "ms"):
        return re.sub(r"\s+", " ", node.get_text()).strip()
    if name == "mo":
        op = re.sub(r"\s+", " ", node.get_text()).strip()
        if not op:
            return ""
        if op in _MATHML_SPACED_OPS:
            return f" {op} "
        if op in (",", ";"):
            return f"{op} "
        return op
    if name == "mspace":
        return " "

    tag_children = [c for c in node.children if isinstance(c, Tag)]

    if name == "mfrac" and len(tag_children) >= 2:
        num = _wrap_if_compound(_mathml_to_text(tag_children[0]))
        den = _wrap_if_compound(_mathml_to_text(tag_children[1]))
        return f"{num} / {den}"
    if name == "msub" and len(tag_children) >= 2:
        base = _mathml_to_text(tag_children[0]).strip()
        sub = _mathml_to_text(tag_children[1]).strip()
        return f"{base}_{sub}_" if sub else base
    if name == "msup" and len(tag_children) >= 2:
        base = _mathml_to_text(tag_children[0]).strip()
        sup = _mathml_to_text(tag_children[1]).strip()
        return f"{base}^{sup}^" if sup else base
    if name == "msubsup" and len(tag_children) >= 3:
        base = _mathml_to_text(tag_children[0]).strip()
        sub = _mathml_to_text(tag_children[1]).strip()
        sup = _mathml_to_text(tag_children[2]).strip()
        out = base
        if sub:
            out += f"_{sub}_"
        if sup:
            out += f"^{sup}^"
        return out
    if name == "msqrt":
        inner = "".join(_mathml_to_text(c) for c in tag_children).strip()
        return f"√({inner})" if inner else ""
    if name == "mroot" and len(tag_children) >= 2:
        base = _mathml_to_text(tag_children[0]).strip()
        idx = _mathml_to_text(tag_children[1]).strip()
        return f"{idx}√({base})" if base else ""
    if name == "mfenced":
        open_ch = node.get("open", "(")
        close_ch = node.get("close", ")")
        sep = node.get("separators", ",")
        sep_ch = (sep[0] + " ") if sep else ", "
        inner = sep_ch.join(
            part for part in (_mathml_to_text(c).strip() for c in tag_children) if part
        )
        return f"{open_ch}{inner}{close_ch}"
    if name == "mtable":
        rows = [
            _mathml_to_text(tr).strip()
            for tr in tag_children
            if (tr.name or "").lower() == "mtr"
        ]
        return "; ".join(r for r in rows if r)
    if name == "mtr":
        cells = [_mathml_to_text(td).strip() for td in tag_children]
        return " ".join(c for c in cells if c)
    if name in ("mover", "munder", "munderover") and tag_children:
        return "".join(_mathml_to_text(c) for c in tag_children)

    parts: list[str] = []
    prev_word = False
    for child in node.children:
        if isinstance(child, NavigableString):
            s = str(child)
            if s.strip():
                parts.append(s)
                prev_word = _ends_with_word(s)
        elif isinstance(child, Tag):
            rendered = _mathml_to_text(child)
            if not rendered:
                continue
            cname = (child.name or "").lower()
            is_word_start = cname in ("mi", "mtext", "mrow") and _starts_with_word(
                rendered
            )
            if prev_word and is_word_start and parts and not parts[-1].endswith(" "):
                parts.append(" ")
            elif (
                cname == "mfrac"
                and parts
                and parts[-1]
                and parts[-1][-1] not in (" ", "(", "[", "{")
            ):
                parts.append(" ")
            parts.append(rendered)
            prev_word = cname in ("mi", "mtext", "mrow") and _ends_with_word(rendered)
    return "".join(parts)


class JATSToMarkdownConverter:
    """Converts JATS XML from NCBI E-utilities / Europe PMC to markdown format."""

    def convert_file(self, xml_file_path: str) -> str:
        """
        Convert a JATS XML file on disk to a markdown string.

        Args:
            xml_file_path: Path to the JATS XML file.

        Returns:
            The markdown content.
        """
        with open(xml_file_path, "r", encoding="utf-8") as f:
            xml_content = f.read()
        return self.convert_xml(xml_content)

    def convert_xml(self, xml_content: str) -> str:
        """
        Convert JATS XML content to a markdown string.

        Args:
            xml_content: The JATS XML content from efetch or Europe PMC.

        Returns:
            The markdown content, or empty string if no <article> element exists.
        """
        soup = BeautifulSoup(xml_content, "xml")

        article = soup.find("article")
        if not article:
            logger.warning("No <article> element found in XML")
            return ""

        parts = []

        # Metadata
        metadata = self._extract_metadata(article)
        parts.append(self._format_metadata(metadata))

        # Abstract
        abstract = self._extract_abstract(article)
        if abstract:
            parts.append(abstract)

        # Body
        body_md = self._extract_body(article)
        if body_md:
            parts.append(body_md)

        # Floating figures/tables (appear in <floats-group> at end of article)
        floats_md = self._extract_floats(article)
        if floats_md:
            parts.append(floats_md)

        # Back matter (acknowledgments, appendices, glossary, notes, back sections)
        back_md = self._extract_back_matter(article)
        if back_md:
            parts.append(back_md)

        # References
        refs = self._extract_references(article)
        if refs:
            parts.append(refs)

        markdown = "\n\n".join(filter(None, parts))
        return self._clean_markdown(markdown)

    def _extract_metadata(self, article: Tag) -> Dict[str, Any]:
        """Extract article metadata from JATS <front>."""
        metadata: Dict[str, Any] = {}
        front = article.find("front")
        if not front:
            return metadata

        meta = front.find("article-meta")
        if not meta:
            return metadata

        # Title
        title_tag = meta.find("article-title")
        if title_tag:
            title_text = self._clean_text(
                self._inline_to_text(title_tag, skip_fn_refs=True)
            )
            if title_text:
                metadata["title"] = title_text

        # Authors (individual and consortium/collab)
        authors = []
        for contrib in meta.find_all("contrib", attrs={"contrib-type": "author"}):
            name_tag = contrib.find(["name", "string-name"])
            if name_tag:
                given = name_tag.find("given-names")
                surname = name_tag.find("surname")
                name_parts = []
                if given:
                    g = self._clean_text(given.get_text())
                    if g:
                        name_parts.append(g)
                if surname:
                    s = self._clean_text(surname.get_text())
                    if s:
                        name_parts.append(s)
                if name_parts:
                    authors.append(" ".join(name_parts))
                else:
                    raw_name = self._clean_text(name_tag.get_text())
                    if raw_name:
                        authors.append(raw_name)
            else:
                collab = contrib.find("collab")
                if collab:
                    collab_text = self._clean_text(collab.get_text())
                    if collab_text:
                        authors.append(collab_text)
        metadata["authors"] = authors

        # Journal
        journal_meta = front.find("journal-meta")
        if journal_meta:
            jt = journal_meta.find("journal-title")
            if jt:
                jt_text = self._clean_text(jt.get_text())
                if jt_text:
                    metadata["journal"] = jt_text

        # DOI
        doi = meta.find("article-id", attrs={"pub-id-type": "doi"})
        if doi and doi.get_text().strip():
            metadata["doi"] = doi.get_text().strip()

        # PMID
        pmid = meta.find("article-id", attrs={"pub-id-type": "pmid"})
        if pmid and pmid.get_text().strip():
            metadata["pmid"] = pmid.get_text().strip()

        # PMCID (NCBI/Europe PMC use either pub-id-type="pmcid" or pub-id-type="pmc")
        pmcid_tag = meta.find(
            "article-id", attrs={"pub-id-type": "pmcid"}
        ) or meta.find("article-id", attrs={"pub-id-type": "pmc"})
        if pmcid_tag and pmcid_tag.get_text().strip():
            raw_pmcid = pmcid_tag.get_text().strip()
            if raw_pmcid.upper().startswith("PMC"):
                metadata["pmcid"] = f"PMC{raw_pmcid[3:]}"
            else:
                metadata["pmcid"] = f"PMC{raw_pmcid}"

        # Publication date (prefer epub/pub, fallback to first <pub-date>)
        pub_date = (
            meta.find("pub-date", attrs={"pub-type": "epub"})
            or meta.find("pub-date", attrs={"date-type": "pub"})
            or meta.find("pub-date")
        )
        if pub_date:
            year = pub_date.find("year")
            month = pub_date.find("month")
            day = pub_date.find("day")
            date_parts = []
            if year and year.get_text().strip():
                date_parts.append(year.get_text().strip())
            if month and month.get_text().strip():
                date_parts.append(month.get_text().strip().zfill(2))
            if day and day.get_text().strip():
                date_parts.append(day.get_text().strip().zfill(2))
            if date_parts:
                metadata["publication_date"] = "/".join(date_parts)

        return metadata

    def _format_metadata(self, metadata: Dict[str, Any]) -> str:
        """Format metadata as markdown header."""
        lines = []

        if metadata.get("title"):
            lines.append(f"# {metadata['title']}")
            lines.append("")

        lines.append("## Metadata")

        if metadata.get("authors"):
            lines.append(f"**Authors:** {', '.join(metadata['authors'])}")

        if metadata.get("journal"):
            lines.append(f"**Journal:** {metadata['journal']}")

        if metadata.get("publication_date"):
            lines.append(f"**Date:** {metadata['publication_date']}")

        if metadata.get("doi"):
            lines.append(
                f"**DOI:** [{metadata['doi']}](https://doi.org/{metadata['doi']})"
            )

        if metadata.get("pmid"):
            lines.append(f"**PMID:** {metadata['pmid']}")

        if metadata.get("pmcid"):
            lines.append(f"**PMCID:** {metadata['pmcid']}")
            lines.append(
                f"**URL:** https://pmc.ncbi.nlm.nih.gov/articles/{metadata['pmcid']}/"
            )

        return "\n".join(lines)

    def _format_single_abstract(self, abstract: Tag, heading: str) -> str:
        """Render one JATS <abstract> element under ``## <heading>``."""
        lines = [f"## {heading}", ""]

        sections = abstract.find_all("sec", recursive=False)
        if sections:
            for sec in sections:
                title = sec.find("title", recursive=False)
                if title:
                    title_text = self._clean_text(title.get_text()).rstrip(":")
                    if title_text:
                        lines.append(f"**{title_text}:** ")
                for p in sec.find_all("p", recursive=False):
                    text = self._process_paragraph(p)
                    if text:
                        lines.append(text)
                        lines.append("")
        else:
            for p in abstract.find_all("p", recursive=False):
                text = self._process_paragraph(p)
                if text:
                    lines.append(text)
                    lines.append("")

        if len(lines) <= 2:
            return ""

        return "\n".join(lines)

    def _extract_abstract(self, article: Tag) -> str:
        """Extract main abstract and substantive secondary abstracts (e.g. Key Points, Author Summary)."""
        front = article.find("front", recursive=False) or article.find("front")
        if not front:
            return ""

        abstracts = front.find_all("abstract")
        if not abstracts:
            return ""

        # Prefer the main abstract (no abstract-type), skipping graphical/TOC/teaser abstracts
        primary = None
        for candidate in abstracts:
            abs_type = (candidate.get("abstract-type") or "").strip().lower()
            if not abs_type:
                primary = candidate
                break
        if primary is None:
            for candidate in abstracts:
                abs_type = (candidate.get("abstract-type") or "").strip().lower()
                if abs_type not in _IGNORED_ABSTRACT_TYPES:
                    primary = candidate
                    break
        if primary is None:
            primary = abstracts[0]

        rendered_parts = []
        primary_md = self._format_single_abstract(primary, "Abstract")
        if primary_md:
            rendered_parts.append(primary_md)

        # Include substantive secondary abstracts (e.g. JAMA Key Points, PLOS Author Summary)
        for candidate in abstracts:
            if candidate is primary:
                continue
            abs_type = (candidate.get("abstract-type") or "").strip().lower()
            if abs_type not in _SECONDARY_ABSTRACT_TITLES:
                continue
            title_tag = candidate.find("title", recursive=False)
            title_text = (
                self._clean_text(self._inline_to_text(title_tag)).rstrip(":")
                if title_tag
                else ""
            )
            heading = title_text or _SECONDARY_ABSTRACT_TITLES[abs_type]
            sec_md = self._format_single_abstract(candidate, heading)
            if sec_md:
                rendered_parts.append(sec_md)

        return "\n\n".join(rendered_parts)

    def _extract_body(self, article: Tag) -> str:
        """Extract main body content from JATS <body>."""
        body = article.find("body")
        if not body:
            return ""

        lines = []
        for child in body.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "sec":
                section_md = self._process_section(child, level=2)
                if section_md:
                    lines.append(section_md)
            elif child.name == "p":
                self._process_p_with_blocks(child, lines)
            elif child.name == "table-wrap":
                table_md = self._process_table_wrap(child)
                if table_md:
                    lines.append(table_md)
            elif child.name == "fig":
                fig_md = self._process_figure(child)
                if fig_md:
                    lines.append(fig_md)
            elif child.name == "list":
                list_md = self._process_list(child)
                if list_md:
                    lines.append(list_md)
                    lines.append("")
            elif child.name == "disp-formula":
                formula = self._process_disp_formula(child)
                if formula:
                    lines.append(formula)
                    lines.append("")
            elif child.name == "disp-quote":
                quote_md = self._process_disp_quote(child)
                if quote_md:
                    lines.append(quote_md)
                    lines.append("")
            elif child.name == "boxed-text":
                box_md = self._process_boxed_text(child, level=2)
                if box_md:
                    lines.append(box_md)
                    lines.append("")
            elif child.name == "supplementary-material":
                sm_md = self._process_supplementary_material(child)
                if sm_md:
                    lines.append(sm_md)
                    next_tag = child.find_next_sibling()
                    if not (next_tag and next_tag.name == "supplementary-material"):
                        lines.append("")

        return "\n".join(lines)

    def _extract_floats(self, article: Tag) -> str:
        """Extract floating figures/tables/boxes from <floats-group>."""
        floats = article.find("floats-group")
        if not floats:
            return ""

        lines = []
        for child in floats.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "fig":
                fig_md = self._process_figure(child)
                if fig_md:
                    lines.append(fig_md)
            elif child.name == "table-wrap":
                table_md = self._process_table_wrap(child)
                if table_md:
                    lines.append(table_md)
            elif child.name == "boxed-text":
                box_md = self._process_boxed_text(child, level=2)
                if box_md:
                    lines.append(box_md)
                    lines.append("")
            elif child.name == "supplementary-material":
                sm_md = self._process_supplementary_material(child)
                if sm_md:
                    lines.append(sm_md)
                    next_tag = child.find_next_sibling()
                    if not (next_tag and next_tag.name == "supplementary-material"):
                        lines.append("")

        return "\n".join(lines)

    def _process_section(self, sec: Tag, level: int = 2) -> str:
        """Process a JATS <sec> element recursively."""
        header_lines = []

        # Section title
        title = sec.find("title", recursive=False)
        if title:
            title_text = self._clean_text(self._inline_to_text(title))
            if title_text:
                prefix = "#" * level
                header_lines.append(f"{prefix} {title_text}")
                header_lines.append("")

        # Process children
        body_lines = []
        for child in sec.children:
            if not isinstance(child, Tag):
                continue

            if child.name == "p":
                self._process_p_with_blocks(child, body_lines)
            elif child.name == "sec":
                subsection = self._process_section(child, level=min(level + 1, 6))
                if subsection:
                    body_lines.append(subsection)
            elif child.name == "table-wrap":
                table_md = self._process_table_wrap(child)
                if table_md:
                    body_lines.append(table_md)
            elif child.name == "fig":
                fig_md = self._process_figure(child)
                if fig_md:
                    body_lines.append(fig_md)
            elif child.name == "list":
                list_md = self._process_list(child)
                if list_md:
                    body_lines.append(list_md)
                    body_lines.append("")
            elif child.name == "disp-formula":
                formula = self._process_disp_formula(child)
                if formula:
                    body_lines.append(formula)
                    body_lines.append("")
            elif child.name == "disp-quote":
                quote_md = self._process_disp_quote(child)
                if quote_md:
                    body_lines.append(quote_md)
                    body_lines.append("")
            elif child.name == "boxed-text":
                box_md = self._process_boxed_text(child, level=min(level + 1, 6))
                if box_md:
                    body_lines.append(box_md)
                    body_lines.append("")
            elif child.name == "supplementary-material":
                sm_md = self._process_supplementary_material(child)
                if sm_md:
                    body_lines.append(sm_md)
                    next_tag = child.find_next_sibling()
                    if not (next_tag and next_tag.name == "supplementary-material"):
                        body_lines.append("")
            elif child.name == "def-list":
                def_md = self._process_def_list(child)
                if def_md:
                    body_lines.append(def_md)
                    body_lines.append("")
            elif child.name == "array":
                table_md = self._convert_table_to_markdown(child)
                if table_md:
                    body_lines.append(table_md)
                    body_lines.append("")
            elif child.name == "fn-group":
                fn_md = self._process_fn_group(child, level=min(level + 1, 6))
                if fn_md:
                    body_lines.append(fn_md)
                    body_lines.append("")

        if not body_lines:
            return ""

        return "\n".join(header_lines + body_lines)

    def _process_boxed_text(self, box: Tag, level: int = 2) -> str:
        """Process a JATS <boxed-text> callout box."""
        header_lines = []
        child_sec_level = level

        label = box.find("label", recursive=False)
        label_text = self._clean_text(label.get_text()) if label else ""

        caption = box.find("caption", recursive=False)
        cap_title_text = ""
        cap_paragraphs = []
        if caption:
            cap_title = caption.find("title", recursive=False)
            if cap_title:
                cap_title_text = self._clean_text(self._inline_to_text(cap_title))
            for cp in caption.find_all("p", recursive=False):
                cp_text = self._process_paragraph(cp)
                if cp_text:
                    cap_paragraphs.append(cp_text)

        if label_text and cap_title_text:
            heading = (
                cap_title_text
                if cap_title_text.lower().startswith(label_text.lower())
                else f"{label_text}: {cap_title_text}"
            )
        else:
            heading = cap_title_text or label_text

        if heading:
            header_lines.append(f"{'#' * level} {heading}")
            header_lines.append("")
            child_sec_level = min(level + 1, 6)

        body_lines = []
        for cp_text in cap_paragraphs:
            body_lines.append(cp_text)
            body_lines.append("")

        for child in box.children:
            if not isinstance(child, Tag) or child.name in ("label", "caption"):
                continue
            if child.name == "sec":
                sub = self._process_section(child, level=child_sec_level)
                if sub:
                    body_lines.append(sub)
            elif child.name == "p":
                self._process_p_with_blocks(child, body_lines)
            elif child.name == "list":
                list_md = self._process_list(child)
                if list_md:
                    body_lines.append(list_md)
                    body_lines.append("")
            elif child.name == "table-wrap":
                table_md = self._process_table_wrap(child)
                if table_md:
                    body_lines.append(table_md)
            elif child.name == "fig":
                fig_md = self._process_figure(child)
                if fig_md:
                    body_lines.append(fig_md)
            elif child.name == "disp-formula":
                formula = self._process_disp_formula(child)
                if formula:
                    body_lines.append(formula)
                    body_lines.append("")
            elif child.name == "disp-quote":
                quote_md = self._process_disp_quote(child)
                if quote_md:
                    body_lines.append(quote_md)
                    body_lines.append("")
            elif child.name == "def-list":
                def_md = self._process_def_list(child)
                if def_md:
                    body_lines.append(def_md)
                    body_lines.append("")
            elif child.name == "array":
                table_md = self._convert_table_to_markdown(child)
                if table_md:
                    body_lines.append(table_md)
                    body_lines.append("")
            elif child.name == "boxed-text":
                nested = self._process_boxed_text(child, level=child_sec_level)
                if nested:
                    body_lines.append(nested)
                    body_lines.append("")
            elif child.name == "supplementary-material":
                sm_md = self._process_supplementary_material(child)
                if sm_md:
                    body_lines.append(sm_md)
                    next_tag = child.find_next_sibling()
                    if not (next_tag and next_tag.name == "supplementary-material"):
                        body_lines.append("")

        if not body_lines:
            return ""

        return "\n".join(header_lines + body_lines)

    def _process_supplementary_material(self, sm: Tag) -> str:
        """Process a JATS <supplementary-material> element into a markdown bullet."""
        label = sm.find("label", recursive=False)
        label_text = self._clean_text(label.get_text()) if label else ""

        cap_parts = []
        caption = sm.find("caption", recursive=False)
        if caption:
            cap_title = caption.find("title", recursive=False)
            if cap_title:
                t = self._clean_text(self._inline_to_text(cap_title))
                if t:
                    cap_parts.append(t)
            for p in caption.find_all("p", recursive=False):
                t = self._process_paragraph(p)
                if t:
                    cap_parts.append(t)
        cap_text = " ".join(cap_parts).strip()

        media = sm.find("media", recursive=False) or sm.find(
            "inline-supplementary-material", recursive=False
        )
        href = ""
        if media:
            href = (media.get("xlink:href") or media.get("href") or "").strip()
        if not href:
            href = (sm.get("xlink:href") or sm.get("href") or "").strip()

        if label_text and cap_text:
            plain_cap = cap_text.lstrip("*").strip()
            if plain_cap.lower().startswith(label_text.lower()):
                desc = cap_text
            else:
                desc = f"**{label_text}:** {cap_text}"
        elif cap_text:
            desc = cap_text
        elif label_text and not label_text.isdigit():
            desc = f"**{label_text}**"
        else:
            desc = ""

        if desc and href:
            return f"- {desc} ({href})"
        if desc:
            return f"- {desc}"
        if href:
            return f"- {href}"
        return ""

    def _process_p_with_blocks(self, p: Tag, lines: list) -> None:
        """Process a <p> that may contain block elements like <table-wrap> or <fig>.

        In JATS XML, block elements (tables, figures) are sometimes nested inside
        <p> elements. This method extracts them and renders them separately from
        the surrounding inline text.
        """
        block_children = p.find_all(_BLOCK_ELEMENTS, recursive=False)

        if not block_children:
            text = self._process_paragraph(p)
            if text:
                lines.append(text)
                lines.append("")
            return

        inline_parts = []

        def flush_inline():
            text = self._clean_text("".join(inline_parts))
            inline_parts.clear()
            if text:
                lines.append(text)
                lines.append("")

        for child in p.children:
            if isinstance(child, NavigableString):
                inline_parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name == "table-wrap":
                    flush_inline()
                    table_md = self._process_table_wrap(child)
                    if table_md:
                        lines.append(table_md)
                elif child.name == "fig":
                    flush_inline()
                    fig_md = self._process_figure(child)
                    if fig_md:
                        lines.append(fig_md)
                elif child.name == "list":
                    flush_inline()
                    list_md = self._process_list(child)
                    if list_md:
                        lines.append(list_md)
                        lines.append("")
                elif child.name == "disp-formula":
                    flush_inline()
                    formula = self._process_disp_formula(child)
                    if formula:
                        lines.append(formula)
                        lines.append("")
                elif child.name == "disp-quote":
                    flush_inline()
                    quote_md = self._process_disp_quote(child)
                    if quote_md:
                        lines.append(quote_md)
                        lines.append("")
                elif child.name == "array":
                    flush_inline()
                    table_md = self._convert_table_to_markdown(child)
                    if table_md:
                        lines.append(table_md)
                        lines.append("")
                elif child.name == "def-list":
                    flush_inline()
                    def_md = self._process_def_list(child)
                    if def_md:
                        lines.append(def_md)
                        lines.append("")
                elif child.name == "boxed-text":
                    flush_inline()
                    box_md = self._process_boxed_text(child, level=3)
                    if box_md:
                        lines.append(box_md)
                        lines.append("")
                elif child.name == "supplementary-material":
                    flush_inline()
                    sm_md = self._process_supplementary_material(child)
                    if sm_md:
                        lines.append(sm_md)
                        next_tag = child.find_next_sibling()
                        if not (next_tag and next_tag.name == "supplementary-material"):
                            lines.append("")
                else:
                    inline_parts.append(self._inline_element_to_text(child))

        flush_inline()

    def _process_disp_formula(self, formula_tag: Tag) -> str:
        """Process a JATS <disp-formula> element (with optional equation <label>)."""
        formula = self._clean_text(self._inline_to_text(formula_tag))
        if not formula:
            return ""
        label = formula_tag.find("label", recursive=False)
        label_text = self._clean_text(label.get_text()) if label else ""
        if label_text and not formula.endswith(label_text):
            return f"{formula} {label_text}"
        return formula

    def _process_disp_quote(self, quote: Tag) -> str:
        """Process a JATS <disp-quote> element into a markdown blockquote."""
        paragraphs = []
        for p in quote.find_all("p", recursive=False):
            text = self._process_paragraph(p)
            if text:
                paragraphs.append(f"> {text}")
        if not paragraphs:
            text = self._clean_text(self._inline_to_text(quote))
            if text:
                paragraphs.append(f"> {text}")
        attrib = quote.find("attrib", recursive=False)
        if attrib:
            attrib_text = self._clean_text(self._inline_to_text(attrib))
            if attrib_text:
                paragraphs.append(f"> — {attrib_text}")
        return "\n>\n".join(paragraphs)

    def _process_paragraph(self, p: Tag) -> str:
        """Process a JATS <p> element with inline markup (no block extraction)."""
        return self._clean_text(self._inline_to_text(p))

    def _inline_element_to_text(self, child: Tag, skip_fn_refs: bool = False) -> str:
        """Convert a single inline JATS element to markdown text."""
        if child.name == "italic":
            inner = self._inline_to_text(child, skip_fn_refs=skip_fn_refs)
            return f"*{inner}*" if inner else ""
        elif child.name == "bold":
            inner = self._inline_to_text(child, skip_fn_refs=skip_fn_refs)
            return f"**{inner}**" if inner else ""
        elif child.name == "sub":
            inner = self._inline_to_text(child, skip_fn_refs=skip_fn_refs)
            return f"_{inner}_" if inner else ""
        elif child.name == "sup":
            inner = self._inline_to_text(child, skip_fn_refs=skip_fn_refs)
            return f"^{inner}^" if inner else ""
        elif child.name == "math":
            return _mathml_to_text(child)
        elif child.name == "alternatives":
            # Prefer MathML over TeX/graphic to avoid duplicating formulas
            math_child = child.find("math", recursive=False)
            if math_child:
                return _mathml_to_text(math_child)
            tex_child = child.find("tex-math", recursive=False)
            if tex_child:
                return self._clean_text(tex_child.get_text())
            for alt_child in child.children:
                if isinstance(alt_child, Tag) and alt_child.name not in (
                    "graphic",
                    "inline-graphic",
                ):
                    return self._inline_element_to_text(
                        alt_child, skip_fn_refs=skip_fn_refs
                    )
            return ""
        elif child.name == "fn" and skip_fn_refs:
            return ""
        elif child.name == "xref":
            ref_type = child.get("ref-type", "")
            if skip_fn_refs and ref_type == "fn":
                return ""
            text = child.get_text().strip()
            if ref_type in ("bibr", "fig", "table", "table-fn"):
                if (
                    text.startswith("[") and text.endswith("]")
                ) or _is_inside_square_brackets(child):
                    return text
                return f"[{text}]"
            return text
        elif child.name in ("ext-link", "uri"):
            href = child.get("xlink:href", child.get("href", ""))
            text = child.get_text().strip()
            if href:
                return f"[{text or href}]({href})"
            return text
        elif child.name in ("break", "br"):
            return " "
        elif child.name in ("title", "label"):
            return ""
        else:
            return self._inline_to_text(child, skip_fn_refs=skip_fn_refs)

    def _inline_to_text(self, element: Tag, skip_fn_refs: bool = False) -> str:
        """Convert JATS inline markup to markdown text."""
        parts = []

        for child in element.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in _BLOCK_ELEMENTS:
                    continue
                parts.append(
                    self._inline_element_to_text(child, skip_fn_refs=skip_fn_refs)
                )

        return "".join(parts)

    def _process_table_wrap(self, tw: Tag) -> str:
        """Process a JATS <table-wrap> element."""
        lines = []

        # Label (e.g., "Table 1")
        label = tw.find("label", recursive=False)
        if label and label.get_text().strip():
            lines.append(f"### {self._clean_text(label.get_text())}")
            lines.append("")

        # Caption
        caption = tw.find("caption", recursive=False)
        if caption:
            cap_text = self._clean_text(caption.get_text())
            if cap_text:
                lines.append(cap_text)
                lines.append("")

        # Table
        table = tw.find("table")
        if table:
            table_md = self._convert_table_to_markdown(table)
            if table_md:
                lines.append(table_md)
                lines.append("")

        # Table footnotes
        for fn in tw.find_all("table-wrap-foot"):
            fn_text = self._clean_text(fn.get_text())
            if fn_text:
                lines.append(f"*{fn_text}*")
                lines.append("")

        return "\n".join(lines)

    def _convert_table_to_markdown(self, table: Tag) -> str:
        """Convert a JATS/HTML <table> to markdown table."""
        return convert_table_to_markdown(table, infer_headers=False)

    def _process_figure(self, fig: Tag) -> str:
        """Process a JATS <fig> element."""
        lines = []

        label = fig.find("label", recursive=False)
        if label and label.get_text().strip():
            lines.append(f"### {self._clean_text(label.get_text())}")
            lines.append("")

        caption = fig.find("caption", recursive=False)
        if caption:
            cap_text = self._clean_text(caption.get_text())
            if cap_text:
                lines.append(cap_text)
                lines.append("")

        # Graphic — build a PMC image URL from the xlink:href
        graphic = fig.find("graphic")
        if graphic:
            href = graphic.get("xlink:href", graphic.get("href", ""))
            if href:
                if href.startswith(("http://", "https://")):
                    img_url = href
                else:
                    ext_re = re.compile(
                        r"\.(?:jpe?g|png|gif|svg|tiff?|webp)$", re.IGNORECASE
                    )
                    filename = href if ext_re.search(href) else f"{href}.jpg"
                    stem = ext_re.sub("", href)
                    img_url = f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{stem}/bin/{filename}"
                label_text = self._clean_text(label.get_text()) if label else "Figure"
                lines.append(f"![{label_text}]({img_url})")
                lines.append("")

        return "\n".join(lines)

    def _process_list(self, list_tag: Tag) -> str:
        """Process a JATS <list> element."""
        lines = []
        list_type = list_tag.get("list-type", "bullet")

        for i, item in enumerate(list_tag.find_all("list-item", recursive=False), 1):
            text = self._clean_text(self._inline_to_text(item))
            if list_type == "order":
                lines.append(f"{i}. {text}")
            else:
                text = re.sub(r"^[\-•–—]\s+", "", text)
                lines.append(f"- {text}")

        return "\n".join(lines)

    def _process_def_list(self, def_list: Tag) -> str:
        """Process a JATS <def-list> (e.g. abbreviations/glossary)."""
        lines = []
        title = def_list.find("title", recursive=False)
        if title:
            title_text = self._clean_text(self._inline_to_text(title)).rstrip(":")
            if title_text:
                lines.append(f"### {title_text}")
                lines.append("")

        for item in def_list.find_all("def-item", recursive=False):
            term = item.find("term")
            definition = item.find("def")
            term_text = self._clean_text(term.get_text()) if term else ""
            def_text = self._clean_text(definition.get_text()) if definition else ""
            if term_text and def_text:
                lines.append(f"- **{term_text}:** {def_text}")
            elif term_text:
                lines.append(f"- **{term_text}**")
            elif def_text:
                lines.append(f"- {def_text}")

        return "\n".join(lines)

    def _process_back_section(
        self, element: Tag, default_title: str = "", level: int = 2
    ) -> str:
        """Process a back-matter container (<ack>, <notes>, <app>, etc.)."""
        lines = []
        title = element.find("title", recursive=False)
        title_text = (
            self._clean_text(self._inline_to_text(title)).rstrip(":") if title else ""
        )
        heading = title_text or default_title
        if heading:
            lines.append(f"{'#' * level} {heading}")
            lines.append("")

        body_lines = []
        for child in element.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "title":
                continue
            elif child.name == "p":
                self._process_p_with_blocks(child, body_lines)
            elif child.name == "sec":
                sub = self._process_section(child, level=min(level + 1, 6))
                if sub:
                    body_lines.append(sub)
            elif child.name == "notes":
                sub = self._process_back_section(
                    child, default_title="", level=min(level + 1, 6)
                )
                if sub:
                    body_lines.append(sub)
                    body_lines.append("")
            elif child.name == "fn-group":
                fn_md = self._process_fn_group(child, level=min(level + 1, 6))
                if fn_md:
                    body_lines.append(fn_md)
                    body_lines.append("")
            elif child.name == "disp-quote":
                quote_md = self._process_disp_quote(child)
                if quote_md:
                    body_lines.append(quote_md)
                    body_lines.append("")
            elif child.name == "table-wrap":
                tbl = self._process_table_wrap(child)
                if tbl:
                    body_lines.append(tbl)
            elif child.name == "fig":
                fig = self._process_figure(child)
                if fig:
                    body_lines.append(fig)
            elif child.name == "list":
                lst = self._process_list(child)
                if lst:
                    body_lines.append(lst)
                    body_lines.append("")
            elif child.name == "def-list":
                dl = self._process_def_list(child)
                if dl:
                    body_lines.append(dl)
                    body_lines.append("")
            elif child.name in ("array", "table"):
                tbl = self._convert_table_to_markdown(child)
                if tbl:
                    body_lines.append(tbl)
                    body_lines.append("")
            elif child.name == "boxed-text":
                box_md = self._process_boxed_text(child, level=min(level + 1, 6))
                if box_md:
                    body_lines.append(box_md)
                    body_lines.append("")
            elif child.name == "supplementary-material":
                sm_md = self._process_supplementary_material(child)
                if sm_md:
                    body_lines.append(sm_md)
                    next_tag = child.find_next_sibling()
                    if not (next_tag and next_tag.name == "supplementary-material"):
                        body_lines.append("")

        if not body_lines:
            return ""

        lines.extend(body_lines)
        return "\n".join(lines)

    def _process_fn_group(self, fn_group: Tag, level: int = 2) -> str:
        """Process a JATS <fn-group> (e.g. disclosures, competing interests, notes)."""
        lines = []
        title = fn_group.find("title", recursive=False)
        title_text = (
            self._clean_text(self._inline_to_text(title)).rstrip(":") if title else ""
        )
        lines.append(f"{'#' * level} {title_text or 'Notes'}")
        lines.append("")

        body_lines = []
        sub_level = min(level + 1, 6)
        for fn in fn_group.find_all("fn", recursive=False):
            fn_title = fn.find("title", recursive=False)
            if fn_title:
                ft = self._clean_text(self._inline_to_text(fn_title)).rstrip(":")
                if ft:
                    body_lines.append(f"{'#' * sub_level} {ft}")
                    body_lines.append("")
            for p in fn.find_all("p", recursive=False):
                self._process_p_with_blocks(p, body_lines)

        if not body_lines:
            return ""

        lines.extend(body_lines)
        return "\n".join(lines)

    def _extract_funding_statement(self, article: Tag) -> str:
        """Extract <funding-statement> elements from <front><article-meta><funding-group>."""
        front = article.find("front")
        if not front:
            return ""
        meta = front.find("article-meta")
        if not meta:
            return ""
        statements = []
        for fg in meta.find_all("funding-group"):
            for fs in fg.find_all("funding-statement"):
                text = self._clean_text(self._inline_to_text(fs))
                if text and text not in statements:
                    statements.append(text)
        if not statements:
            return ""
        return "## Funding\n\n" + "\n\n".join(statements)

    def _extract_back_matter(self, article: Tag) -> str:
        """Extract non-reference sections from JATS <back> (ack, glossary, notes, appendices, etc.)."""
        back = article.find("back")
        sections = []
        has_back_funding = False

        if back:
            for child in back.children:
                if not isinstance(child, Tag) or child.name == "ref-list":
                    continue

                if child.name == "sec":
                    sec_title = child.find("title", recursive=False)
                    if (
                        sec_title and "funding" in sec_title.get_text().strip().lower()
                    ) or (child.get("sec-type") or "").lower() in (
                        "funding-statement",
                        "funding",
                    ):
                        has_back_funding = True
                    md = self._process_section(child, level=2)
                    if md:
                        sections.append(md)
                elif child.name == "ack":
                    md = self._process_back_section(
                        child, default_title="Acknowledgments"
                    )
                    if md:
                        sections.append(md)
                elif child.name == "notes":
                    notes_title = child.find("title", recursive=False)
                    if (child.get("notes-type") or "").lower() in (
                        "funding-information",
                        "funding",
                        "funding-statement",
                    ) or (
                        notes_title
                        and "funding" in notes_title.get_text().strip().lower()
                    ):
                        has_back_funding = True
                    md = self._process_back_section(child, default_title="Notes")
                    if md:
                        sections.append(md)
                elif child.name == "glossary":
                    md = self._process_back_section(
                        child, default_title="Abbreviations"
                    )
                    if md:
                        sections.append(md)
                elif child.name == "app-group":
                    for app in child.find_all("app", recursive=False):
                        # If <app> directly wraps <sec> without its own <title>, avoid a redundant "## Appendix" heading
                        app_title = app.find("title", recursive=False)
                        if app_title:
                            md = self._process_back_section(
                                app, default_title="Appendix"
                            )
                        else:
                            md = self._process_back_section(app, default_title="")
                        if md:
                            sections.append(md)
                elif child.name == "fn-group":
                    md = self._process_fn_group(child)
                    if md:
                        sections.append(md)

        if not has_back_funding:
            funding_md = self._extract_funding_statement(article)
            if funding_md:
                sections.append(funding_md)

        return "\n\n".join(sections)

    def _extract_references(self, article: Tag) -> str:
        """Extract references from JATS <back>."""
        back = article.find("back")
        if not back:
            return ""

        ref_list = back.find("ref-list")
        if not ref_list:
            return ""

        lines = ["## References", ""]

        for i, ref in enumerate(ref_list.find_all("ref"), 1):
            ref_md = self._process_reference(ref, i)
            if ref_md:
                lines.append(ref_md)
                lines.append("")

        if len(lines) <= 2:
            return ""

        return "\n".join(lines)

    def _process_reference(self, ref: Tag, num: int) -> str:
        """Process a single JATS <ref> element."""
        citation = ref.find(["element-citation", "mixed-citation", "nlm-citation"])
        if not citation:
            text = self._clean_text(ref.get_text())
            return f"{num}. {text}" if text else ""

        parts = []

        # Authors (<name>, <string-name>, or <collab>)
        authors = []
        for name in citation.find_all(["name", "string-name", "collab"]):
            if name.find_parent(["name", "string-name", "collab"]):
                continue
            if name.name == "collab":
                collab_text = self._clean_text(name.get_text())
                if collab_text:
                    authors.append(collab_text)
                continue
            surname = name.find("surname")
            given = name.find("given-names")
            if surname:
                author = self._clean_text(surname.get_text())
                if given and given.get_text().strip():
                    author += f" {self._clean_text(given.get_text())}"
                if author:
                    authors.append(author)
            else:
                raw_name = self._clean_text(name.get_text())
                if raw_name:
                    authors.append(raw_name)
        etal = citation.find("etal")

        if authors:
            author_str = ", ".join(authors)
            if etal:
                author_str += " et al."
            parts.append(author_str)

        # Title
        article_title = citation.find("article-title")
        if article_title:
            title_text = self._clean_text(self._inline_to_text(article_title))
            if title_text:
                parts.append(title_text)

        # Source (journal)
        source = citation.find("source")
        if source and source.get_text().strip():
            parts.append(f"*{self._clean_text(source.get_text())}*")

        # Volume, year
        vol = citation.find("volume")
        year = citation.find("year")
        extra = []
        if vol and vol.get_text().strip():
            extra.append(f"**{self._clean_text(vol.get_text())}**")
        if year and year.get_text().strip():
            extra.append(f"({self._clean_text(year.get_text())})")
        if extra:
            parts.append(" ".join(extra))

        # Pages (or electronic location ID when fpage is absent)
        fpage = citation.find("fpage")
        lpage = citation.find("lpage")
        elocation = citation.find("elocation-id")
        if fpage and fpage.get_text().strip():
            page_str = self._clean_text(fpage.get_text())
            if lpage and lpage.get_text().strip():
                page_str += f"-{self._clean_text(lpage.get_text())}"
            parts.append(page_str)
        elif elocation and elocation.get_text().strip():
            parts.append(self._clean_text(elocation.get_text()))

        # External identifier links
        links = []
        doi = citation.find("pub-id", attrs={"pub-id-type": "doi"})
        if doi and doi.get_text().strip():
            links.append(f"[DOI](https://doi.org/{doi.get_text().strip()})")

        pmid = citation.find("pub-id", attrs={"pub-id-type": "pmid"})
        if pmid and pmid.get_text().strip():
            links.append(
                f"[PubMed](https://pubmed.ncbi.nlm.nih.gov/{pmid.get_text().strip()})"
            )

        pmcid = citation.find(
            "pub-id", attrs={"pub-id-type": "pmcid"}
        ) or citation.find("pub-id", attrs={"pub-id-type": "pmc"})
        if pmcid and pmcid.get_text().strip():
            raw_pmc = pmcid.get_text().strip()
            norm_pmc = raw_pmc if raw_pmc.upper().startswith("PMC") else f"PMC{raw_pmc}"
            links.append(f"[PMC](https://pmc.ncbi.nlm.nih.gov/articles/{norm_pmc}/)")

        if not parts:
            # Fallback for unstructured <mixed-citation> text
            raw_text = self._clean_text(citation.get_text())
            if not raw_text:
                return ""
            if links:
                return f"{num}. {raw_text} {' | '.join(links)}"
            return f"{num}. {raw_text}"

        base = _join_citation_parts(parts)
        if links:
            sep = " " if base.endswith((".", "?", "!")) else ". "
            return f"{num}. {base}{sep}{' | '.join(links)}"
        return f"{num}. {base}"

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _clean_markdown(self, markdown: str) -> str:
        """Clean up final markdown output."""
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip() + "\n"
