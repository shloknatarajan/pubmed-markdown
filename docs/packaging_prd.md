# PubMed Downloader - Packaging PRD

## Overview

This document outlines the requirements and implementation plan for converting the PMid Article Resolver project into a distributable Python package. The goal is to enable users to install and use the `PubMedMarkdown` class and related functionality via pip installation.

## Objectives

1. **Pip Package**: Create a distributable package that users can install via `pip install pubmed-downloader`
2. **Importable Module**: Enable clean imports like `from pubmed-downloader import PubMedMarkdown`
3. **Maintain Current Functionality**: Preserve all existing CLI and API functionality

## Current State Analysis

### Strengths
- Well-structured modular code in `src/` directory
- Clear class-based architecture with `PubMedMarkdown` as main entry point
- Comprehensive documentation and examples
- Proper dependency management via `pixi.toml`

### Gaps for Packaging
- No `setup.py` or `pyproject.toml` for pip distribution
- No package structure for proper imports
- Dependencies not specified in pip-compatible format
- No entry points defined for CLI usage

## Implementation Requirements

### 1. Package Structure Conversion

**Current Structure:**
```
src/
├── __init__.py
├── pubmed_downloader.py
├── pmcid_from_pmid.py
├── html_from_pmcid.py
├── markdown_from_html.py
└── manage_records.py
```

**Target Structure:**
```
pmid_article_resolver/
├── __init__.py
├── downloader.py (renamed from pubmed_downloader.py)
├── pmcid_resolver.py (renamed from pmcid_from_pmid.py)
├── html_extractor.py (renamed from html_from_pmcid.py)
├── markdown_converter.py (renamed from markdown_from_html.py)
└── record_manager.py (renamed from manage_records.py)
```

### 2. Package Configuration

**Create `pyproject.toml`:**
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pmid-article-resolver"
version = "0.1.0"
description = "Convert PubMed articles from PMIDs to clean, structured markdown format"
readme = "README.md"
authors = [{name = "Shlok Natarajan", email = "shlok.natarajan@gmail.com"}]
license = {text = "MIT"}
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Topic :: Scientific/Engineering :: Bio-Informatics",
]
keywords = ["pubmed", "markdown", "research", "bioinformatics"]
dependencies = [
    "requests>=2.32.3",
    "beautifulsoup4>=4.13.4",
    "pandas>=2.2.3",
    "loguru>=0.7.3",
    "biopython>=1.85",
    "tqdm>=4.67.1",
    "python-dotenv>=1.1.0",
]
requires-python = ">=3.8"

[project.urls]
"Homepage" = "https://github.com/daneshjou-lab/pmid-article-resolver"
"Bug Reports" = "https://github.com/daneshjou-lab/pmid-article-resolver/issues"
"Source" = "https://github.com/daneshjou-lab/pmid-article-resolver"

[project.scripts]
pmid-resolver = "pmid_article_resolver.cli:main"

[project.optional-dependencies]
dev = ["black>=25.1.0", "pytest>=7.0.0"]
```

### 3. Main Package Entry Points

**Update `pmid_article_resolver/__init__.py`:**
```python
"""PMid Article Resolver - Convert PubMed articles to markdown format."""

from .downloader import PubMedMarkdown
from .pmcid_resolver import get_pmcid_from_pmid
from .html_extractor import get_html_from_pmcid
from .markdown_converter import PubMedHTMLToMarkdownConverter
from .record_manager import get_scraped_pmids, create_records

__version__ = "0.1.0"
__all__ = [
    "PubMedMarkdown",
    "get_pmcid_from_pmid", 
    "get_html_from_pmcid",
    "PubMedHTMLToMarkdownConverter",
    "get_scraped_pmids",
    "create_records"
]
```

### 4. CLI Entry Point

**Create `pmid_article_resolver/cli.py`:**
```python
"""Command line interface for PMid Article Resolver."""

import argparse
from .downloader import convert_pmids_from_file
from .markdown_converter import convert_local_html_to_markdown
from .record_manager import update_records

def main():
    parser = argparse.ArgumentParser(description="PMid Article Resolver CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Convert PMIDs command
    convert_parser = subparsers.add_parser("convert", help="Convert PMIDs to markdown")
    convert_parser.add_argument("--file", required=True, help="File containing PMIDs")
    convert_parser.add_argument("--output", default="data", help="Output directory")
    convert_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    
    # Convert HTML command  
    html_parser = subparsers.add_parser("convert-html", help="Convert local HTML to markdown")
    html_parser.add_argument("--input", default="data", help="Input directory containing HTML")
    
    # Update records command
    records_parser = subparsers.add_parser("update-records", help="Update processing records")
    records_parser.add_argument("--dir", default="data", help="Data directory")
    
    args = parser.parse_args()
    
    if args.command == "convert":
        convert_pmids_from_file(args.file, args.output, args.overwrite)
    elif args.command == "convert-html":
        convert_local_html_to_markdown(args.input)
    elif args.command == "update-records":
        update_records(args.dir)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
```

## Implementation Plan

### Phase 1: Minimum Viable Package (MVP)
**Goal**: Enable `pip install` and basic imports

1. **Restructure package** (2 hours)
   - Rename `src/` to `pmid_article_resolver/`
   - Update all internal imports
   - Create proper `__init__.py` with exports

2. **Create packaging configuration** (1 hour)
   - Add `pyproject.toml` with metadata and dependencies
   - Update `README.md` with installation instructions

3. **Test local installation** (1 hour)
   - Build package: `python -m build`
   - Install locally: `pip install -e .`
   - Verify imports work: `from pmid_article_resolver import PubMedMarkdown`

### Phase 2: Full Distribution (Extended)
**Goal**: Publish to PyPI and add advanced features

4. **Add CLI entry points** (2 hours)
   - Create `cli.py` module
   - Define console scripts in `pyproject.toml`
   - Test CLI commands

5. **Distribution setup** (2 hours)
   - Create PyPI account and API tokens
   - Upload to TestPyPI first
   - Publish to production PyPI

6. **Documentation updates** (1 hour)
   - Update README with pip installation
   - Add usage examples for package imports
   - Create release notes

## Usage Examples After Implementation

### Installation
```bash
pip install pmid-article-resolver
```

### Python API Usage
```python
from pmid_article_resolver import PubMedMarkdown

# Initialize downloader
downloader = PubMedMarkdown()

# Convert single PMID to markdown (in-memory)
markdown = downloader.single_pmid_to_markdown("12895196")

# Batch convert PMIDs (saves to files)
pmids = ["12895196", "17872605"] 
downloader.pmids_to_markdown(pmids, save_dir="output/")
```

### CLI Usage
```bash
# Convert PMIDs from file
pmid-resolver convert --file pmids.txt --output data/

# Convert existing HTML files
pmid-resolver convert-html --input data/

# Update processing records
pmid-resolver update-records --dir data/
```

## Migration Strategy

### Backwards Compatibility
- Keep current `pixi` setup working alongside pip package
- Maintain existing file-based CLI commands
- Preserve all current API signatures

### Testing Plan
1. **Unit Tests**: Test all imports work correctly
2. **Integration Tests**: Verify end-to-end workflows
3. **CLI Tests**: Validate command line functionality
4. **Installation Tests**: Test pip install on clean environments

## Success Criteria

### Minimum Viable Package (MVP)
- ✅ Users can install via `pip install pmid-article-resolver`
- ✅ Basic import works: `from pmid_article_resolver import PubMedMarkdown`
- ✅ Core functionality preserved
- ✅ Existing pixi workflow still functional

### Full Distribution
- ✅ CLI commands work via `pmid-resolver` entry point
- ✅ Package published to PyPI
- ✅ Documentation updated with pip installation
- ✅ All existing functionality preserved
- ✅ Comprehensive testing coverage

## Estimated Timeline

- **MVP (Phase 1)**: 4 hours
- **Full Distribution (Phase 2)**: 5 hours  
- **Total**: 9 hours over 2-3 development sessions

## Dependencies

- No external dependencies beyond current project requirements
- Build tools: `setuptools`, `wheel`, `build` (for development)
- Optional: `twine` for PyPI uploads