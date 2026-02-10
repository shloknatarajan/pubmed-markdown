# PubMed PMCID/PMID to Markdown Converter

A comprehensive tool for converting PubMed articles from article PMIDs to clean, structured markdown format. This project automatically handles the entire pipeline from PMID to full-text markdown, including PMCID resolution, HTML extraction, and intelligent content conversion.

## Overview

This tool enables researchers to:
- Convert PubMed article PMIDs to full-text markdown
- Preserve scientific content including tables, figures, equations, and references
- Maintain local caches for performance
- Track processing records and metadata

## Features

- **Complete Pipeline**: PMID → PMCID → HTML → Markdown
- **Intelligent Caching**: Avoids redundant API calls with configurable cache expiry
- **Batch Processing**: Efficient handling of multiple articles
- **Content Preservation**: Tables, figures, citations, and mathematical equations
- **Robust Error Handling**: Graceful failure handling and logging
- **Record Management**: Track processing status and metadata
- **PharmGKB Integration**: Extract PMIDs from PharmGKB variant annotations for pharmacogenomics research

## Installation

This project uses [Pixi](https://pixi.sh/) for dependency management:

```bash
# Install dependencies
pixi install

# Activate the environment
pixi shell
```

## Setup

1. Create a `.env` file in the project root:
```env
NCBI_EMAIL=your-email@institution.edu
```

2. Ensure required directories exist (created automatically):
```
data/
├── html/          # Raw HTML files from PMC
├── markdown/      # Converted markdown files
├── cache/         # PMID to PMCID mapping cache
└── records.csv    # Processing records
```

## Usage

### Command Line Interface

**Convert PMIDs from a file:**
```bash
# Using pixi task
pixi run convert-local-pmids

# Or directly
python -m src.pubmed_downloader --file_path=data/pmids.txt --save_dir=data
```

**Convert existing HTML to markdown:**
This converts HTML found at data/html to markdown
```bash
# Using pixi task  
pixi run convert-local-html

# Or directly
python -m src.markdown_from_html
```

**Update processing records:**
This keeps track of conversions and what you have downloaded
```bash
# Using pixi task
pixi run update-records

# Or directly
python -m src.manage_records
```

**Generate PharmGKB PMID list:**
This downloads PharmGKB variant annotations and extracts PMIDs
```bash
# Using pixi task (if defined)
pixi run pharmgkb-pmids

# Or directly
python -m src.pharmgkb_annotations
```

### Python API

**In-memory processing (no files created):**
```python
from src.pubmed_downloader import PubMedDownloader

converter = PubMedDownloader()
# Returns markdown string directly - no files saved
markdown = converter.single_pmid_to_markdown("12895196")
print(markdown)
```

**File-based processing (saves to disk):**
```python
from src.pubmed_downloader import PubMedDownloader

converter = PubMedDownloader()
pmids = ["12895196", "17872605", "25051018"]
# Downloads HTML and saves both HTML and markdown files to data/ directory
converter.pmids_to_markdown(pmids, save_dir="data")
```

#### Key Differences

| Function | Creates Files | Returns Content | Use Case |
|----------|---------------|-----------------|----------|
| `single_pmid_to_markdown()` | No | Returns markdown string | Quick conversions, API usage, testing |
| `pmids_to_markdown()` | Yes | None | Batch processing, building datasets, archival |
| `local_html_to_markdown()` | Yes | None | Converting existing HTML files |
| `pmcids_to_html()` | Yes | None | Downloading HTML for later processing |

**File-based functions** create organized directory structures:
- `data/html/` - Raw HTML files from PMC  
- `data/markdown/` - Converted markdown files
- `data/cache/` - PMID→PMCID mapping cache
- `data/records.csv` - Processing metadata

**In-memory functions** return content directly without creating files, ideal for programmatic use or when you only need the converted text.

**Working with records:**
```python
from src.manage_records import get_scraped_pmids, create_records

# Get all processed PMIDs
pmids = get_scraped_pmids()

# Regenerate records from markdown files
records = create_records()
```

**Working with PharmGKB data:**
```python
from src.pharmgkb_annotations import get_pmid_list, variant_annotations_pipeline

# Get PMIDs from PharmGKB variant annotations
pmids = get_pmid_list()
print(f"Found {len(pmids)} unique PMIDs from PharmGKB")

# Run complete pipeline (download + extract PMIDs)
variant_annotations_pipeline(override=False, save_dir="data")
```

## PharmGKB Integration Tutorial

This section demonstrates how to use the PharmGKB functionality to download pharmacogenomics literature from PharmGKB's curated variant annotations.

### Step 1: Extract PMIDs from PharmGKB

```python
from src.pharmgkb_annotations import get_pmid_list, variant_annotations_pipeline

# Download PharmGKB variant annotations and extract PMIDs
pmids = get_pmid_list(save_dir="data")
print(f"Extracted {len(pmids)} unique PMIDs from PharmGKB variant annotations")
```

This will:
1. Download the PharmGKB variant annotations ZIP file (~20MB)
2. Extract the `var_drug_ann.tsv` file containing variant-drug associations
3. Extract all unique PMIDs and save them to `data/pharmgkb_pmids.txt`
4. Return the list of PMIDs for further processing

### Step 2: Convert PharmGKB PMIDs to Markdown

```python
from src.pubmed_downloader import PubMedDownloader
from src.pharmgkb_annotations import get_pmid_list

# Get PharmGKB PMIDs
pharmgkb_pmids = get_pmid_list(save_dir="data")

# Convert to string format (PubMedDownloader expects strings)
pmid_strings = [str(pmid) for pmid in pharmgkb_pmids]

# Process through the complete pipeline
converter = PubMedDownloader()
converter.pmids_to_markdown(pmid_strings, save_dir="data")
```

### Step 3: Complete PharmGKB Pipeline

For a complete workflow, you can combine both steps:

```python
from src.pharmgkb_annotations import variant_annotations_pipeline, get_pmid_list
from src.pubmed_downloader import PubMedDownloader

# Step 1: Download PharmGKB data and extract PMIDs
print("Downloading PharmGKB variant annotations...")
variant_annotations_pipeline(save_dir="data")

# Step 2: Get the PMID list
pmids = get_pmid_list(save_dir="data")
pmid_strings = [str(pmid) for pmid in pmids[:50]]  # Process first 50 for testing

# Step 3: Convert to markdown
print(f"Converting {len(pmid_strings)} PMIDs to markdown...")
converter = PubMedDownloader()
converter.pmids_to_markdown(pmid_strings, save_dir="data")

print("PharmGKB pipeline complete!")
```

### Command Line Workflow

```bash
# 1. Download PharmGKB data and extract PMIDs
python -m src.pharmgkb_annotations

# 2. Copy PMIDs to the standard input file
cp data/pharmgkb_pmids.txt data/pmids.txt

# 3. Convert PMIDs to markdown using existing pipeline
pixi run convert-local-pmids

# 4. Update processing records
pixi run update-records
```

### What You Get

After running the PharmGKB pipeline, you'll have:

- **`data/variantAnnotations/`**: Raw PharmGKB variant annotation data
- **`data/pharmgkb_pmids.txt`**: List of unique PMIDs from PharmGKB (~2000+ articles)
- **`data/html/`**: Raw HTML files for successfully downloaded articles
- **`data/markdown/`**: Converted markdown files for pharmacogenomics literature
- **`data/records.csv`**: Processing metadata and status tracking

This creates a comprehensive dataset of pharmacogenomics literature in clean, structured markdown format suitable for research, analysis, or building knowledge bases.

## Core Components

### 1. PubMedDownloader (`src/pubmed_downloader.py`)
Main orchestrator class that handles the complete pipeline:
- PMID to PMCID conversion
- HTML extraction from PMC
- Markdown conversion
- File management and caching

### 2. PMCID Resolution (`src/pmcid_from_pmid.py`)
Converts PMIDs to PMCIDs using NCBI's ID Converter API:
- Batch processing with configurable delays
- Intelligent caching with expiry
- Rate limiting to respect NCBI guidelines

### 3. HTML Extraction (`src/html_from_pmcid.py`)
Fetches raw HTML content from PubMed Central using PMCIDs.

### 4. HTML to Markdown Conversion (`src/markdown_from_html.py`)
Converts PMC HTML to clean markdown:
- Preserves scientific content structure
- Handles tables, figures, and equations
- Maintains citation integrity
- Extracts metadata and references

### 5. Record Management (`src/manage_records.py`)
Tracks processing status and metadata:
- Creates records from existing markdown files
- Validates data completeness
- Manages processing history

### 6. PharmGKB Integration (`src/pharmgkb_annotations.py`)
Downloads and processes PharmGKB variant annotations:
- Downloads variant annotations from PharmGKB API
- Extracts unique PMIDs from pharmacogenomics literature
- Integrates with the main conversion pipeline

## Output Format

Generated markdown files include:

```markdown
# Article Title

**Authors:** Author 1, Author 2  
**Journal:** Journal Name  
**DOI:** https://doi.org/...  
**PMID:** 12345678  
**PMCID:** PMC1234567  
**URL:** https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/

## Abstract
[Abstract content with preserved formatting]

## Introduction
[Introduction content]

## Methods
[Methods with subsections]

### Table 1: Characteristics
| Variable | Value |
|----------|-------|
| Sample   | Data  |

### Figure 1: Results
![Figure 1](https://cdn.ncbi.nlm.nih.gov/pmc/blobs/...)
Figure caption with detailed description.

## Results
[Results content with cross-references]

## Discussion
[Discussion content]

## References
1. Author et al. Title. *Journal*. Year. [DOI](link) [PMC](link) [PubMed](link)
2. [Additional references...]
```

## Examples for Testing

| PMID | PMCID | Link | Notes |
|------|-------|------|-------|
| 12895196 | PMC1884285 | https://pmc.ncbi.nlm.nih.gov/articles/PMC1884285/ | Intervention study |
| 17872605 | PMC1952551 | https://pmc.ncbi.nlm.nih.gov/articles/PMC1952551/ | Case study |
| 25051018 | PMC4381041 | https://pmc.ncbi.nlm.nih.gov/articles/PMC4381041/ | Research article |

## Configuration

### Environment Variables
- `NCBI_EMAIL`: Required for NCBI API access
- `PMID_CACHE_DIR`: Cache directory (default: `data/cache`)
- `PMID_CACHE_FILE`: Cache filename (default: `pmid_to_pmcid.json`)

### Pixi Tasks

The project includes several predefined pixi tasks for common operations:

- **`pixi run update-records`**: Scans the `data/markdown/` directory and updates the `data/records.csv` file with metadata from all processed articles. This is useful for regenerating records after manual file operations or to ensure consistency.

- **`pixi run convert-local-html`**: Processes all HTML files in the `data/html/` directory and converts them to markdown format. Saves output to `data/markdown/`. This is ideal when you have already downloaded HTML files and want to convert them in batch.

- **`pixi run convert-local-pmids`**: Reads PMIDs from `data/pmids.txt` (one per line) and processes them through the complete pipeline: PMID → PMCID → HTML → Markdown. Creates organized output in the `data/` directory structure.

## Error Handling

The tool includes comprehensive error handling:
- **Missing PMCIDs**: Logs warnings for PMIDs without PMC coverage
- **Network Issues**: Retries with exponential backoff
- **Malformed HTML**: Graceful degradation with content extraction
- **File I/O Errors**: Detailed logging and recovery options

## Performance Features

- **Caching**: PMID→PMCID mappings cached for 30 days
- **Batch Processing**: API calls optimized for NCBI rate limits
- **Incremental Processing**: Skips already-processed files
- **Parallel Operations**: Concurrent file operations where possible

## Contributing

The project follows standard Python conventions:
- Type hints throughout
- Comprehensive logging with loguru
- Error handling at all API boundaries
- Modular design for easy extension

## Dependencies

Key dependencies managed through Pixi:
- `requests`: HTTP client for API calls
- `beautifulsoup4`: HTML parsing and conversion
- `pandas`: Data management and records
- `loguru`: Structured logging
- `biopython`: Bioinformatics utilities
- `tqdm`: Progress bars
- `python-dotenv`: Environment configuration

## Troubleshooting

**Common Issues:**
1. **No PMCID found**: Not all PMIDs have PMC coverage
2. **Network timeouts**: Check internet connection and NCBI API status
3. **Missing markdown content**: Verify HTML extraction was successful
4. **Cache issues**: Clear `data/cache/` directory if needed

**Debugging:**
- Check logs for detailed error messages
- Verify `.env` file configuration
- Ensure sufficient disk space for output files
- Test with known working PMIDs first

## Todos:
- Have the PMID to PMCID converter utilize the cache as well
