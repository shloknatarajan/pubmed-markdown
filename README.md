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

**Single article (returns markdown string, no files created):**

```python
from pubmed_markdown import PubMedMarkdown

downloader = PubMedMarkdown()

# From PMID (resolves to PMCID automatically, falls back to abstract if not open access)
markdown = downloader.single_pmid_to_markdown("12895196")

# From PMCID directly
markdown = downloader.single_pmcid_to_markdown("PMC1884285")
```

**Batch processing (saves HTML and markdown files to disk):**

```python
from pubmed_markdown import PubMedMarkdown

downloader = PubMedMarkdown()
pmids = ["12895196", "17872605", "25051018"]
downloader.pmids_to_markdown(pmids, save_dir="data")
```

This creates:
```
data/
├── html/          # Raw HTML from PMC
├── markdown/      # Converted markdown files
├── cache/         # PMID-to-PMCID mapping cache
└── pmcids.txt     # Resolved PMCIDs
```

**Add supplementary materials to existing markdown files:**

```python
downloader.add_supplements_to_existing(save_dir="data")
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

# Add supplementary materials to existing markdown
pubmed-download --add_supplements --save_dir=data

# Clear all caches
pubmed-download --clear_caches
```

### API Reference

| Method | Creates Files | Returns | Use Case |
|--------|--------------|---------|----------|
| `single_pmid_to_markdown()` | No | Markdown string | Single article, programmatic use |
| `single_pmcid_to_markdown()` | No | Markdown string | Direct PMCID conversion |
| `pmids_to_markdown()` | Yes | None | Batch processing, building datasets |
| `local_html_to_markdown()` | Yes | None | Re-convert existing HTML files |
| `add_supplements_to_existing()` | Yes | None | Append supplements to existing markdown |

## PharmGKB Integration

Extract PMIDs from PharmGKB variant annotations for pharmacogenomics research:

```python
from pubmed_markdown.pharmgkb_annotations import get_pmid_list
from pubmed_markdown import PubMedMarkdown

# Download PharmGKB annotations and extract PMIDs
pmids = get_pmid_list(save_dir="data")

# Convert to markdown
downloader = PubMedMarkdown()
downloader.pmids_to_markdown([str(p) for p in pmids], save_dir="data")
```

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
