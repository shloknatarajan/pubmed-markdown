"""
JATS XML to Markdown Converter

Converts JATS/NLM XML (as returned by NCBI E-utilities efetch for PMC articles)
to structured markdown format.
"""

import re
import html
from typing import Dict

from bs4 import BeautifulSoup, Tag, NavigableString
from loguru import logger

# Block-level JATS elements that can appear inside <p> but should be
# extracted and rendered separately (not as inline text).
_BLOCK_ELEMENTS = {"table-wrap", "fig", "disp-formula", "list"}


class JATSToMarkdownConverter:
    """Converts JATS XML from NCBI E-utilities to markdown format."""

    def convert_xml(self, xml_content: str) -> str:
        """
        Convert JATS XML content to markdown string.

        Args:
            xml_content: The JATS XML content from efetch

        Returns:
            The markdown content
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

        # References
        refs = self._extract_references(article)
        if refs:
            parts.append(refs)

        markdown = "\n\n".join(filter(None, parts))
        return self._clean_markdown(markdown)

    def _extract_metadata(self, article: Tag) -> Dict[str, str]:
        """Extract article metadata from JATS <front>."""
        metadata = {}
        front = article.find("front")
        if not front:
            return metadata

        meta = front.find("article-meta")
        if not meta:
            return metadata

        # Title
        title_tag = meta.find("article-title")
        if title_tag:
            metadata["title"] = self._inline_to_text(title_tag)

        # Authors
        authors = []
        for contrib in meta.find_all("contrib", attrs={"contrib-type": "author"}):
            name_tag = contrib.find("name")
            if name_tag:
                given = name_tag.find("given-names")
                surname = name_tag.find("surname")
                name_parts = []
                if given:
                    name_parts.append(given.get_text())
                if surname:
                    name_parts.append(surname.get_text())
                if name_parts:
                    authors.append(" ".join(name_parts))
        metadata["authors"] = authors

        # Journal
        journal_meta = front.find("journal-meta")
        if journal_meta:
            jt = journal_meta.find("journal-title")
            if jt:
                metadata["journal"] = jt.get_text().strip()

        # DOI
        doi = meta.find("article-id", attrs={"pub-id-type": "doi"})
        if doi:
            metadata["doi"] = doi.get_text().strip()

        # PMID
        pmid = meta.find("article-id", attrs={"pub-id-type": "pmid"})
        if pmid:
            metadata["pmid"] = pmid.get_text().strip()

        # PMCID
        pmcid = meta.find("article-id", attrs={"pub-id-type": "pmcid"})
        if pmcid:
            metadata["pmcid"] = pmcid.get_text().strip()

        # Publication date
        pub_date = meta.find("pub-date")
        if pub_date:
            year = pub_date.find("year")
            month = pub_date.find("month")
            day = pub_date.find("day")
            date_parts = []
            if year:
                date_parts.append(year.get_text())
            if month:
                date_parts.append(month.get_text().zfill(2))
            if day:
                date_parts.append(day.get_text().zfill(2))
            if date_parts:
                metadata["publication_date"] = "/".join(date_parts)

        return metadata

    def _format_metadata(self, metadata: Dict[str, str]) -> str:
        """Format metadata as markdown header."""
        lines = []

        if "title" in metadata:
            lines.append(f"# {metadata['title']}")
            lines.append("")

        lines.append("## Metadata")

        if "authors" in metadata and metadata["authors"]:
            lines.append(f"**Authors:** {', '.join(metadata['authors'])}")

        if "journal" in metadata:
            lines.append(f"**Journal:** {metadata['journal']}")

        if "publication_date" in metadata:
            lines.append(f"**Date:** {metadata['publication_date']}")

        if "doi" in metadata:
            lines.append(
                f"**DOI:** [{metadata['doi']}](https://doi.org/{metadata['doi']})"
            )

        if "pmid" in metadata:
            lines.append(f"**PMID:** {metadata['pmid']}")

        if "pmcid" in metadata:
            lines.append(f"**PMCID:** {metadata['pmcid']}")
            lines.append(
                f"**URL:** https://pmc.ncbi.nlm.nih.gov/articles/{metadata['pmcid']}/"
            )

        return "\n".join(lines)

    def _extract_abstract(self, article: Tag) -> str:
        """Extract abstract from JATS."""
        front = article.find("front")
        if not front:
            return ""
        abstract = front.find("abstract")
        if not abstract:
            return ""

        lines = ["## Abstract", ""]

        # Structured abstract with <sec> children
        sections = abstract.find_all("sec", recursive=False)
        if sections:
            for sec in sections:
                title = sec.find("title", recursive=False)
                if title:
                    title_text = title.get_text().strip().rstrip(":")
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

        return "\n".join(lines)

    def _extract_body(self, article: Tag) -> str:
        """Extract main body content from JATS."""
        body = article.find("body")
        if not body:
            return ""

        lines = []
        for sec in body.find_all("sec", recursive=False):
            section_md = self._process_section(sec, level=2)
            if section_md:
                lines.append(section_md)

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
            title_text = self._inline_to_text(title)
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
                formula = self._inline_to_text(child)
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
            # Simple paragraph — no embedded blocks
            text = self._process_paragraph(p)
            if text:
                lines.append(text)
                lines.append("")
            return

        # Walk through children, collecting inline runs and emitting blocks
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
                    formula = self._inline_to_text(child)
                    if formula:
                        lines.append(formula)
                        lines.append("")
                else:
                    # Normal inline element
                    inline_parts.append(self._inline_element_to_text(child))

        flush_inline()

    def _process_paragraph(self, p: Tag) -> str:
        """Process a JATS <p> element with inline markup (no block extraction)."""
        return self._clean_text(self._inline_to_text(p))

    def _inline_element_to_text(self, child: Tag) -> str:
        """Convert a single inline JATS element to markdown text."""
        if child.name == "italic":
            return f"*{child.get_text()}*"
        elif child.name == "bold":
            return f"**{child.get_text()}**"
        elif child.name == "sub":
            return f"_{child.get_text()}_"
        elif child.name == "sup":
            return f"^{child.get_text()}^"
        elif child.name == "xref":
            ref_type = child.get("ref-type", "")
            text = child.get_text().strip()
            if ref_type == "bibr":
                return f"[{text}]"
            elif ref_type in ("fig", "table", "table-fn"):
                return f"[{text}]"
            else:
                return text
        elif child.name == "ext-link":
            href = child.get("xlink:href", child.get("href", ""))
            text = child.get_text().strip()
            if href:
                return f"[{text}]({href})"
            else:
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
                    # Skip block elements in inline context — they are handled
                    # by _process_p_with_blocks at a higher level.
                    continue
                parts.append(self._inline_element_to_text(child))

        return "".join(parts)

    def _process_table_wrap(self, tw: Tag) -> str:
        """Process a JATS <table-wrap> element."""
        lines = []

        # Label (e.g., "Table 1")
        label = tw.find("label", recursive=False)
        if label:
            lines.append(f"### {label.get_text().strip()}")
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
                    colspan = int(cell.get("colspan", 1))
                    text = self._clean_text(cell.get_text()).replace("|", "\\|").replace("\n", " ")
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
                body_rows = body_rows[len(header_rows):]

        for row in body_rows:
            cells = row.find_all(["td", "th"])
            row_data = []
            for cell in cells:
                colspan = int(cell.get("colspan", 1))
                text = self._clean_text(cell.get_text()).replace("|", "\\|").replace("\n", " ")
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
            lines.append("| " + " | ".join(row[:len(header)]) + " |")

        return "\n".join(lines)

    def _process_figure(self, fig: Tag) -> str:
        """Process a JATS <fig> element."""
        lines = []

        label = fig.find("label", recursive=False)
        if label:
            lines.append(f"### {label.get_text().strip()}")
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
                # xlink:href is typically a PMC media ID like "nihms-1518655-f0001"
                # Construct the actual PMC image URL
                img_url = f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{href}/bin/{href}.jpg"
                label_text = label.get_text().strip() if label else "Figure"
                lines.append(f"![{label_text}]({img_url})")
                lines.append("")

        return "\n".join(lines)

    def _process_list(self, list_tag: Tag) -> str:
        """Process a JATS <list> element."""
        lines = []
        list_type = list_tag.get("list-type", "bullet")

        for i, item in enumerate(list_tag.find_all("list-item", recursive=False), 1):
            text = self._clean_text(item.get_text())
            if list_type == "order":
                lines.append(f"{i}. {text}")
            else:
                lines.append(f"- {text}")

        return "\n".join(lines)

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

        return "\n".join(lines)

    def _process_reference(self, ref: Tag, num: int) -> str:
        """Process a single JATS <ref> element."""
        citation = ref.find(["element-citation", "mixed-citation", "nlm-citation"])
        if not citation:
            # Fallback to raw text
            text = self._clean_text(ref.get_text())
            return f"{num}. {text}" if text else ""

        parts = []

        # Authors
        authors = []
        for name in citation.find_all("name"):
            surname = name.find("surname")
            given = name.find("given-names")
            if surname:
                author = surname.get_text()
                if given:
                    author += f" {given.get_text()}"
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
            parts.append(self._inline_to_text(article_title))

        # Source (journal)
        source = citation.find("source")
        if source and source.get_text().strip():
            parts.append(f"*{source.get_text().strip()}*")

        # Volume, year
        vol = citation.find("volume")
        year = citation.find("year")
        extra = []
        if vol:
            extra.append(f"**{vol.get_text()}**")
        if year:
            extra.append(f"({year.get_text()})")
        if extra:
            parts.append(" ".join(extra))

        # Pages
        fpage = citation.find("fpage")
        lpage = citation.find("lpage")
        if fpage:
            page_str = fpage.get_text()
            if lpage:
                page_str += f"-{lpage.get_text()}"
            parts.append(page_str)

        # DOI link
        doi = citation.find("pub-id", attrs={"pub-id-type": "doi"})
        if doi:
            parts.append(f"[DOI](https://doi.org/{doi.get_text().strip()})")

        # PMID link
        pmid = citation.find("pub-id", attrs={"pub-id-type": "pmid"})
        if pmid:
            parts.append(
                f"[PubMed](https://pubmed.ncbi.nlm.nih.gov/{pmid.get_text().strip()})"
            )

        return f"{num}. {'. '.join(parts)}" if parts else ""

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
