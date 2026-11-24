# PubMed Downloader

[![PyPI](https://img.shields.io/pypi/v/pubmed-markdown)](https://pypi.org/project/pubmed-markdown/)

Convert PubMed articles to clean, structured markdown. Handles the full pipeline: PMID resolution, full-text extraction via PubMed Central, HTML-to-markdown conversion, and supplementary material retrieval.

Articles without open-access full text automatically fall back to abstract-only download.

## Installation

```bash
pip install pubmed-markdown
```

Requires Python 3.11+.

## Setup

Set your email for NCBI API identification (required to avoid 403 errors):

```bash
export NCBI_EMAIL=your-email@institution.edu
```

Or pass them directly:

```python
downloader = PubMedMarkdown(
    email="your-email@institution.edu",
    ncbi_key="your-ncbi-api-key",  # optional; raises rate limit from 3 to 10 req/s
)
```

## Quick Start

```python
from pubmed_markdown import PubMedMarkdown

downloader = PubMedMarkdown()

# Get markdown string from a PMID
markdown = downloader.pmid_to_markdown("12895196")
```

## Usage

### Python API

**Get markdown strings (single or batch, no files created):**

```python
from pubmed_markdown import PubMedMarkdown

downloader = PubMedMarkdown()

# From PMID — accepts a single string or a list
markdown = downloader.pmid_to_markdown("12895196")
markdowns = downloader.pmid_to_markdown(["12895196", "17872605"])

# From PMCID directly — also accepts a single string or a list
markdown = downloader.pmcid_to_markdown("PMC1884285")
markdowns = downloader.pmcid_to_markdown(["PMC1884285", "PMC6435416"])

# Skip supplementary materials
markdown = downloader.pmid_to_markdown("12895196", include_supplements=False)
```

**Save markdown files to disk (single or batch):**

```python
from pubmed_markdown import PubMedMarkdown

downloader = PubMedMarkdown()
downloader.pmids_to_markdown_files(["12895196", "17872605"], save_dir="data")

# Also works with a single PMID
downloader.pmids_to_markdown_files("25051018", save_dir="data")

# Overwrite existing files
downloader.pmids_to_markdown_files(["12895196"], save_dir="data", overwrite=True)
```

This creates:
```
data/
├── html/          # Raw HTML from PMC
└── markdown/      # Converted markdown files
```

Full-text articles are saved as `{PMCID}.md`. Articles without open-access full text are saved as `PMID{PMID}.md` with abstract only.

**Individual utility functions:**

```python
from pubmed_markdown import (
    get_pmcid_from_pmid,
    get_html_from_pmcid,
    get_abstract_markdown_from_pmid,
    fetch_bioc_supplement,
    format_supplement_as_markdown,
)

# Resolve PMIDs to PMCIDs (returns dict mapping PMID -> PMCID or None)
mapping = get_pmcid_from_pmid(["12895196", "17872605"])

# Fetch raw HTML from PMC
html = get_html_from_pmcid("PMC1884285")

# Get abstract for non-open-access articles
abstract_md = get_abstract_markdown_from_pmid("12345678")

# Get raw supplementary material text
supplement = fetch_bioc_supplement("PMC6435416")

# Get supplementary materials formatted as a markdown section
supplement_md = format_supplement_as_markdown("PMC6435416")
```

### Command Line

```bash
# Convert PMIDs from a file (one PMID per line)
pubmed-download --file_path=pmids.txt --save_dir=data

# Overwrite existing files
pubmed-download --file_path=pmids.txt --save_dir=data --overwrite

# Specify email directly
pubmed-download --file_path=pmids.txt --email=your-email@institution.edu
```

### API Reference

| Method | Creates Files | Returns | Use Case |
|--------|--------------|---------|----------|
| `pmid_to_markdown()` | No | Markdown string(s) | Single or batch, programmatic use |
| `pmcid_to_markdown()` | No | Markdown string(s) | Direct PMCID conversion |
| `pmids_to_markdown_files()` | Yes | None | Batch processing, building datasets |
| `pmids_to_pmcids()` | No | List of PMCIDs | PMID to PMCID resolution |
| `pmcids_to_html()` | Yes | None | Fetch and save raw HTML |
| `local_html_to_markdown()` | Yes | None | Re-convert existing HTML files |

All methods accepting IDs take either a single string or a list of strings.

## How It Works

1. **PMID to PMCID** -- Uses NCBI's ID Converter API with batching and rate limiting
2. **Multi-tier full-text extraction** -- By default (`source="auto"`), fetches JATS XML via NCBI E-utilities `efetch` (no WAF, works from cloud IPs), falls back to Europe PMC `fullTextXML`, and falls back to PMC HTML for publisher XML opt-outs or scanned articles. Pass `source="html_first"`, `"xml"`, or `"html"` to customize the tier order.
3. **Markdown conversion** -- Converts JATS XML or PMC HTML to a consistent structured markdown schema preserving tables, figures, citations, and references
4. **Supplementary materials** -- Fetches pre-processed supplement text via NCBI's BioC API
5. **Abstract fallback** -- Articles not in PMC Open Access get abstract + metadata via NCBI E-Fetch

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `NCBI_EMAIL` | None | Email for NCBI API identification |
| `NCBI_API_KEY` | None | Optional NCBI API key (increases E-utilities rate limit from 3 to 10 req/s) |

## License

MIT
