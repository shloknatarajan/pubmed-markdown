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

# Block-level JATS elements that can appear inside <p> but should be
# extracted and rendered separately (not as inline text).
_BLOCK_ELEMENTS = {"table-wrap", "fig", "disp-formula", "list", "array", "def-list"}
_IGNORED_ABSTRACT_TYPES = {"graphical", "toc", "teaser"}


def _safe_colspan(cell: Tag) -> int:
    """Safely parse a table cell's colspan attribute as a positive int."""
    raw = cell.get("colspan", 1)
    try:
        value = int(raw)
        return max(1, value)
    except (TypeError, ValueError):
        return 1


class JATSToMarkdownConverter:
    """Converts JATS XML from NCBI E-utilities / Europe PMC to markdown format."""

    def __init__(self):
        self.soup = None

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
        self.soup = BeautifulSoup(xml_content, "xml")

        article = self.soup.find("article")
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
            title_text = self._clean_text(self._inline_to_text(title_tag))
            if title_text:
                metadata["title"] = title_text

        # Authors (individual and consortium/collab)
        authors = []
        for contrib in meta.find_all("contrib", attrs={"contrib-type": "author"}):
            name_tag = contrib.find("name")
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

    def _extract_abstract(self, article: Tag) -> str:
        """Extract abstract from JATS <front>."""
        front = article.find("front")
        if not front:
            return ""

        abstracts = front.find_all("abstract")
        if not abstracts:
            return ""

        # Prefer the main abstract (no abstract-type), skipping graphical/TOC abstracts
        abstract = None
        for candidate in abstracts:
            abs_type = (candidate.get("abstract-type") or "").strip().lower()
            if not abs_type:
                abstract = candidate
                break
        if abstract is None:
            for candidate in abstracts:
                abs_type = (candidate.get("abstract-type") or "").strip().lower()
                if abs_type not in _IGNORED_ABSTRACT_TYPES:
                    abstract = candidate
                    break
        if abstract is None:
            abstract = abstracts[0]

        lines = ["## Abstract", ""]

        # Structured abstract with <sec> children
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
            # Simple abstract
            for p in abstract.find_all("p", recursive=False):
                text = self._process_paragraph(p)
                if text:
                    lines.append(text)
                    lines.append("")

        if len(lines) <= 2:
            return ""

        return "\n".join(lines)

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
                formula = self._clean_text(self._inline_to_text(child))
                if formula:
                    lines.append(formula)
                    lines.append("")

        return "\n".join(lines)

    def _extract_floats(self, article: Tag) -> str:
        """Extract floating figures/tables from <floats-group>."""
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

        return "\n".join(lines)

    def _process_section(self, sec: Tag, level: int = 2) -> str:
        """Process a JATS <sec> element recursively."""
        lines = []

        # Section title
        title = sec.find("title", recursive=False)
        if title:
            title_text = self._clean_text(self._inline_to_text(title))
            if title_text:
                prefix = "#" * level
                lines.append(f"{prefix} {title_text}")
                lines.append("")

        # Process children
        for child in sec.children:
            if not isinstance(child, Tag):
                continue

            if child.name == "p":
                self._process_p_with_blocks(child, lines)
            elif child.name == "sec":
                subsection = self._process_section(child, level=min(level + 1, 6))
                if subsection:
                    lines.append(subsection)
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
                formula = self._clean_text(self._inline_to_text(child))
                if formula:
                    lines.append(formula)
                    lines.append("")

        return "\n".join(lines)

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
                    formula = self._clean_text(self._inline_to_text(child))
                    if formula:
                        lines.append(formula)
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
                else:
                    inline_parts.append(self._inline_element_to_text(child))

        flush_inline()

    def _process_paragraph(self, p: Tag) -> str:
        """Process a JATS <p> element with inline markup (no block extraction)."""
        return self._clean_text(self._inline_to_text(p))

    def _inline_element_to_text(self, child: Tag) -> str:
        """Convert a single inline JATS element to markdown text."""
        if child.name == "italic":
            inner = self._inline_to_text(child)
            return f"*{inner}*" if inner else ""
        elif child.name == "bold":
            inner = self._inline_to_text(child)
            return f"**{inner}**" if inner else ""
        elif child.name == "sub":
            return f"_{child.get_text()}_"
        elif child.name == "sup":
            return f"^{child.get_text()}^"
        elif child.name == "xref":
            ref_type = child.get("ref-type", "")
            text = child.get_text().strip()
            if ref_type in ("bibr", "fig", "table", "table-fn"):
                return f"[{text}]"
            return text
        elif child.name in ("ext-link", "uri"):
            href = child.get("xlink:href", child.get("href", ""))
            text = child.get_text().strip()
            if href:
                return f"[{text or href}]({href})"
            return text
        elif child.name in ("title", "label"):
            return ""
        else:
            return self._inline_to_text(child)

    def _inline_to_text(self, element: Tag) -> str:
        """Convert JATS inline markup to markdown text."""
        parts = []

        for child in element.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in _BLOCK_ELEMENTS:
                    continue
                parts.append(self._inline_element_to_text(child))

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
        rows = []
        max_cols = 0

        # Process header
        thead = table.find("thead")
        header_rows = []
        if thead:
            header_rows = thead.find_all("tr")
            for row in header_rows:
                cells = row.find_all(["th", "td"])
                row_data = []
                for cell in cells:
                    colspan = _safe_colspan(cell)
                    text = (
                        self._clean_text(cell.get_text())
                        .replace("|", "\\|")
                        .replace("\n", " ")
                    )
                    if not text:
                        text = " "
                    row_data.append(text)
                    for _ in range(colspan - 1):
                        row_data.append("")
                rows.append(row_data)
                max_cols = max(max_cols, len(row_data))

        # Process body
        tbody = table.find("tbody")
        if tbody:
            body_rows = tbody.find_all("tr")
        else:
            body_rows = table.find_all("tr")
            if header_rows:
                body_rows = body_rows[len(header_rows) :]

        for row in body_rows:
            cells = row.find_all(["td", "th"])
            row_data = []
            for cell in cells:
                colspan = _safe_colspan(cell)
                text = (
                    self._clean_text(cell.get_text())
                    .replace("|", "\\|")
                    .replace("\n", " ")
                )
                if not text:
                    text = " "
                row_data.append(text)
                for _ in range(colspan - 1):
                    row_data.append("")
            rows.append(row_data)
            max_cols = max(max_cols, len(row_data))

        if not rows:
            return ""

        # Normalize column count
        for row in rows:
            while len(row) < max_cols:
                row.append("")

        # Build markdown table
        lines = []
        header = rows[0]
        data_rows = rows[1:]

        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in data_rows:
            while len(row) < len(header):
                row.append("")
            lines.append("| " + " | ".join(row[: len(header)]) + " |")

        return "\n".join(lines)

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
                    img_url = f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{href}/bin/{href}.jpg"
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

        if not body_lines:
            return ""

        lines.extend(body_lines)
        return "\n".join(lines)

    def _process_fn_group(self, fn_group: Tag) -> str:
        """Process a JATS <fn-group> (e.g. disclosures, competing interests, notes)."""
        lines = []
        title = fn_group.find("title", recursive=False)
        title_text = (
            self._clean_text(self._inline_to_text(title)).rstrip(":") if title else ""
        )
        lines.append(f"## {title_text or 'Notes'}")
        lines.append("")

        body_lines = []
        for fn in fn_group.find_all("fn", recursive=False):
            fn_title = fn.find("title", recursive=False)
            if fn_title:
                ft = self._clean_text(self._inline_to_text(fn_title)).rstrip(":")
                if ft:
                    body_lines.append(f"### {ft}")
                    body_lines.append("")
            for p in fn.find_all("p", recursive=False):
                self._process_p_with_blocks(p, body_lines)

        if not body_lines:
            return ""

        lines.extend(body_lines)
        return "\n".join(lines)

    def _extract_back_matter(self, article: Tag) -> str:
        """Extract non-reference sections from JATS <back> (ack, glossary, notes, appendices, etc.)."""
        back = article.find("back")
        if not back:
            return ""

        sections = []
        for child in back.children:
            if not isinstance(child, Tag) or child.name == "ref-list":
                continue

            if child.name == "sec":
                md = self._process_section(child, level=2)
                if md:
                    sections.append(md)
            elif child.name == "ack":
                md = self._process_back_section(child, default_title="Acknowledgments")
                if md:
                    sections.append(md)
            elif child.name == "notes":
                md = self._process_back_section(child, default_title="Notes")
                if md:
                    sections.append(md)
            elif child.name == "glossary":
                md = self._process_back_section(child, default_title="Abbreviations")
                if md:
                    sections.append(md)
            elif child.name == "app-group":
                for app in child.find_all("app", recursive=False):
                    # If <app> directly wraps <sec> without its own <title>, avoid a redundant "## Appendix" heading
                    app_title = app.find("title", recursive=False)
                    if app_title:
                        md = self._process_back_section(app, default_title="Appendix")
                    else:
                        md = self._process_back_section(app, default_title="")
                    if md:
                        sections.append(md)
            elif child.name == "fn-group":
                md = self._process_fn_group(child)
                if md:
                    sections.append(md)

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

        # Authors
        authors = []
        for name in citation.find_all("name"):
            surname = name.find("surname")
            given = name.find("given-names")
            if surname:
                author = self._clean_text(surname.get_text())
                if given and given.get_text().strip():
                    author += f" {self._clean_text(given.get_text())}"
                if author:
                    authors.append(author)
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

        # Pages
        fpage = citation.find("fpage")
        lpage = citation.find("lpage")
        if fpage and fpage.get_text().strip():
            page_str = self._clean_text(fpage.get_text())
            if lpage and lpage.get_text().strip():
                page_str += f"-{self._clean_text(lpage.get_text())}"
            parts.append(page_str)

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

        base = ". ".join(parts)
        if links:
            return f"{num}. {base}. {' | '.join(links)}"
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
