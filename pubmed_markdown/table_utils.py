"""
Shared HTML/JATS table-to-Markdown conversion utilities.

Handles 2D grid layout for ``colspan`` and ``rowspan``, multi-row ``<thead>``
header merging, multiple ``<tbody>`` sections, and clean line-break spacing
inside table cells.
"""

import html
import re
from typing import Dict, List, Tuple

from bs4 import NavigableString, Tag

_BREAK_CELL_TAGS = {"break", "br"}
_BLOCK_CELL_TAGS = {"p", "div", "li"}


def _safe_span(cell: Tag, attr: str) -> int:
    """Safely parse a table cell's colspan or rowspan attribute as a positive int."""
    raw = cell.get(attr, 1)
    try:
        value = int(raw)
        return max(1, value)
    except (TypeError, ValueError):
        return 1


def extract_cell_text(cell: Tag) -> str:
    """Extract clean single-line text from a table cell.

    Converts ``<break/>``, ``<br>``, and block boundaries (``<p>``, ``<div>``,
    ``<li>``) to spaces so multi-line cells do not glue adjacent tokens together,
    while keeping inline elements (``<sub>``, ``<sup>``, ``<italic>``, etc.)
    contiguous.
    """
    parts: List[str] = []

    def _walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in _BREAK_CELL_TAGS:
                    parts.append(" ")
                elif child.name in _BLOCK_CELL_TAGS:
                    parts.append(" ")
                    _walk(child)
                    parts.append(" ")
                else:
                    _walk(child)

    _walk(cell)
    text = html.unescape("".join(parts))
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("|", "\\|")


def _expand_tr_rows(
    tr_list: List[Tag],
) -> Tuple[List[List[str]], Dict[Tuple[int, int], Tuple[str, bool]]]:
    """Expand a sequence of ``<tr>`` rows into a 2D grid honoring rowspan & colspan.

    Returns:
        grid: 2D list of cell strings (spanned continuation slots are ``""``).
        span_map: maps ``(row_idx, col_idx)`` to ``(text, is_primary)`` for
            horizontal ``colspan`` origins and continuations (used when merging
            multi-row ``<thead>`` headers).
    """
    grid: List[List[str]] = []
    occupied: Dict[Tuple[int, int], str] = {}
    span_map: Dict[Tuple[int, int], Tuple[str, bool]] = {}

    for r_idx, tr in enumerate(tr_list):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            cells = tr.find_all(["th", "td"])

        row: List[str] = []
        col_idx = 0

        def _consume_occupied() -> None:
            nonlocal col_idx
            while (r_idx, col_idx) in occupied:
                row.append(occupied[(r_idx, col_idx)])
                col_idx += 1

        for cell in cells:
            _consume_occupied()
            colspan = _safe_span(cell, "colspan")
            rowspan = _safe_span(cell, "rowspan")
            text = extract_cell_text(cell)

            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr == 0 and dc == 0:
                        row.append(text)
                        span_map[(r_idx, col_idx)] = (text, True)
                    elif dr == 0:
                        row.append("")
                        span_map[(r_idx, col_idx + dc)] = (text, False)
                    else:
                        occupied[(r_idx + dr, col_idx + dc)] = ""

            col_idx += colspan

        _consume_occupied()
        grid.append(row)

    return grid, span_map


def _merge_header_rows(
    header_grid: List[List[str]],
    span_map: Dict[Tuple[int, int], Tuple[str, bool]],
    num_cols: int,
) -> List[str]:
    """Merge multi-row ``<thead>`` grid into a single aligned header row."""
    if len(header_grid) == 1:
        row = list(header_grid[0])
        while len(row) < num_cols:
            row.append("")
        return row[:num_cols]

    # Pad header rows to uniform width
    padded = [r + [""] * (num_cols - len(r)) for r in header_grid]
    num_rows = len(padded)
    merged: List[str] = []

    for c in range(num_cols):
        col_parts: List[str] = []
        for r in range(num_rows):
            primary = padded[r][c]
            if primary:
                if not col_parts or col_parts[-1] != primary:
                    col_parts.append(primary)
            elif (r, c) in span_map:
                span_text, is_primary = span_map[(r, c)]
                if not is_primary and span_text:
                    # Only propagate a parent colspan label into this column if
                    # a lower header row defines a subheader in this column.
                    has_subheader = any(padded[r2][c] for r2 in range(r + 1, num_rows))
                    if has_subheader and (not col_parts or col_parts[-1] != span_text):
                        col_parts.append(span_text)
        merged.append(" - ".join(col_parts))

    return merged


def convert_table_to_markdown(table: Tag, infer_headers: bool = False) -> str:
    """Convert an HTML or JATS ``<table>`` (or ``<array>``) to a Markdown table.

    Args:
        table: BeautifulSoup ``Tag`` for ``<table>`` or ``<array>``.
        infer_headers: When True and no ``<thead>`` is present, synthesize
            generic headers if the first row appears purely numeric.

    Returns:
        Markdown table string, or empty string if the table has no rows.
    """
    thead = table.find("thead", recursive=False) or table.find("thead")
    header_trs = thead.find_all("tr", recursive=False) if thead else []
    if thead and not header_trs:
        header_trs = thead.find_all("tr")

    header_grid: List[List[str]] = []
    header_span_map: Dict[Tuple[int, int], Tuple[str, bool]] = {}
    if header_trs:
        header_grid, header_span_map = _expand_tr_rows(header_trs)

    # Collect body rows across one or more <tbody> sections (plus optional <tfoot>)
    body_grid: List[List[str]] = []
    tbodies = table.find_all("tbody", recursive=False)
    if not tbodies:
        first_tbody = table.find("tbody")
        if first_tbody:
            tbodies = [first_tbody]

    if tbodies:
        for tb in tbodies:
            trs = tb.find_all("tr", recursive=False) or tb.find_all("tr")
            if trs:
                g, _ = _expand_tr_rows(trs)
                body_grid.extend(g)
    else:
        direct_trs = table.find_all("tr", recursive=False)
        if direct_trs:
            trs = [tr for tr in direct_trs if tr not in header_trs]
        else:
            all_trs = table.find_all("tr")
            header_set = set(id(tr) for tr in header_trs)
            trs = [tr for tr in all_trs if id(tr) not in header_set]
        if trs:
            g, _ = _expand_tr_rows(trs)
            body_grid.extend(g)

    tfoot = table.find("tfoot", recursive=False)
    if tfoot:
        foot_trs = tfoot.find_all("tr", recursive=False) or tfoot.find_all("tr")
        if foot_trs:
            g, _ = _expand_tr_rows(foot_trs)
            body_grid.extend(g)

    all_rows = header_grid + body_grid
    if not all_rows:
        return ""

    max_cols = max((len(r) for r in all_rows), default=0)
    if max_cols == 0:
        return ""

    if header_grid:
        header = _merge_header_rows(header_grid, header_span_map, max_cols)
        data_rows = body_grid
    else:
        first_row = body_grid[0]
        if infer_headers and not any(
            not cell.replace(".", "").replace("-", "").isdigit() and cell.strip()
            for cell in first_row
        ):
            header = ["Category"] + [f"Value {i}" for i in range(1, max_cols)]
            data_rows = body_grid
        else:
            header = list(first_row)
            data_rows = body_grid[1:]

    # Normalize column widths
    while len(header) < max_cols:
        header.append("")
    header = header[:max_cols]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * max_cols) + " |",
    ]
    for row in data_rows:
        padded_row = row + [""] * (max_cols - len(row))
        lines.append("| " + " | ".join(padded_row[:max_cols]) + " |")

    return "\n".join(lines)
