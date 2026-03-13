# PubMed Downloader

[![PyPI](https://img.shields.io/pypi/v/pubmed-markdown)](https://pypi.org/project/pubmed-markdown/)

Convert PubMed articles to clean, structured markdown. Handles the full pipeline: PMID resolution, full-text extraction via PubMed Central, HTML-to-markdown conversion, and supplementary material retrieval.

Articles without open-access full text automatically fall back to abstract-only download.

## Installation

```bash
pip install pubmed-markdown
```

## Setup

Set your email for NCBI API identification (optional but recommended):

```bash
export NCBI_EMAIL=your-email@institution.edu
```

Or create a `.env` file in your working directory:

```env
NCBI_EMAIL=your-email@institution.edu
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
markdown = downloader.pmcids_to_markdown("PMC1884285")
markdowns = downloader.pmcids_to_markdown(["PMC1884285", "PMC6435416"])
```

**Save markdown files to disk (single or batch):**

```python
from pubmed_markdown import PubMedMarkdown

downloader = PubMedMarkdown()
downloader.pmids_to_markdown_files(["12895196", "17872605"], save_dir="data")

# Also works with a single PMID
downloader.pmids_to_markdown_files("25051018", save_dir="data")
```

This creates:
```
data/
├── html/          # Raw HTML from PMC
└── markdown/      # Converted markdown files

~/.cache/pubmed-markdown/
└── pmid_to_pmcid.json  # PMID-to-PMCID mapping cache
```

**Individual utility functions:**

```python
from pubmed_markdown import (
    get_pmcid_from_pmid,
    get_html_from_pmcid,
    get_abstract_markdown_from_pmid,
    fetch_bioc_supplement,
)

# Resolve PMIDs to PMCIDs
mapping = get_pmcid_from_pmid(["12895196", "17872605"])

# Fetch raw HTML from PMC
html = get_html_from_pmcid("PMC1884285")

# Get abstract for non-open-access articles
abstract_md = get_abstract_markdown_from_pmid("12345678")

# Get supplementary material text
supplement = fetch_bioc_supplement("PMC6435416")
```

### Command Line

```bash
# Convert PMIDs from a file (one PMID per line)
pubmed-download --file_path=pmids.txt --save_dir=data

# Clear all caches
pubmed-download --clear_caches
```

### API Reference

| Method | Creates Files | Returns | Use Case |
|--------|--------------|---------|----------|
| `pmid_to_markdown()` | No | Markdown string(s) | Single or batch, programmatic use |
| `pmcids_to_markdown()` | No | Markdown string(s) | Direct PMCID conversion |
| `pmids_to_markdown_files()` | Yes | None | Batch processing, building datasets |
| `local_html_to_markdown()` | Yes | None | Re-convert existing HTML files |

All methods accepting IDs take either a single string or a list of strings.

## How It Works

1. **PMID to PMCID** -- Uses NCBI's ID Converter API with batching, caching (30-day expiry), and rate limiting
2. **HTML extraction** -- Fetches full article HTML from PubMed Central
3. **Markdown conversion** -- Converts HTML to structured markdown preserving tables, figures, citations, and references
4. **Supplementary materials** -- Fetches pre-processed supplement text via NCBI's BioC API
5. **Abstract fallback** -- Articles not in PMC Open Access get abstract + metadata via NCBI E-Fetch

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `NCBI_EMAIL` | None | Email for NCBI API identification |
| `PMID_CACHE_DIR` | `data/cache` | Cache directory path |
| `PMID_CACHE_FILE` | `pmid_to_pmcid.json` | Cache filename |

## License

MIT
