"""
PubMed Markdown — Tutorial
===========================

This tutorial walks through the main features of pubmed-markdown:
converting PubMed articles into clean, structured markdown.

Before running, install the package:

    pip install pubmed-markdown

And (optionally) set your NCBI email for API identification:

    export NCBI_EMAIL=your-email@institution.edu
"""

from pubmed_markdown import (
    PubMedMarkdown,
    get_pmcid_from_pmid,
    get_html_from_pmcid,
    get_abstract_markdown_from_pmid,
    fetch_bioc_supplement,
)

# ---------------------------------------------------------------------------
# 1. Quick start — convert a single article by PMID
# ---------------------------------------------------------------------------
# This is the simplest way to get markdown from a PubMed article.
# It resolves the PMID to a PMCID, fetches the full text, and converts
# it to markdown. If the article isn't open-access, it falls back to
# the abstract automatically.
#
# Set include_supplements=True (the default) to append supplementary
# material text from NCBI's BioC API at the end of the markdown.

downloader = PubMedMarkdown()

markdown = downloader.pmid_to_markdown("12895196", include_supplements=True)
if markdown:
    print("=== Single article (by PMID, with supplements) ===")
    print(markdown[:500])  # print first 500 chars
    print("...\n")

# ---------------------------------------------------------------------------
# 2. Convert a single article by PMCID
# ---------------------------------------------------------------------------
# If you already have a PMCID, you can skip PMID resolution entirely.
# Both pmcids_to_markdown and pmid_to_markdown accept a single string
# or a list of strings.

markdown = downloader.pmcids_to_markdown("PMC1884285", include_supplements=True)
if markdown:
    print("=== Single article (by PMCID, with supplements) ===")
    print(markdown[:500])
    print("...\n")

# ---------------------------------------------------------------------------
# 3. Batch processing — save HTML and markdown files to disk
# ---------------------------------------------------------------------------
# For larger workloads, use pmids_to_markdown(). This saves raw HTML
# and converted markdown into a directory structure:
#
#   data/
#   ├── html/          # Raw HTML from PubMed Central
#   └── markdown/      # Converted markdown files
#
# Supplementary materials are included by default in the saved markdown.
# Articles without open-access full text are saved as abstract-only
# markdown (named PMID<id>.md).

pmids = ["12895196", "17872605", "25051018"]
downloader.pmids_to_markdown_files(pmids, save_dir="tutorial_output")
print("=== Batch processing complete — check tutorial_output/ ===\n")

# ---------------------------------------------------------------------------
# 4. Lower-level utilities
# ---------------------------------------------------------------------------
# You can also use the individual pipeline steps directly.

# 4a. Resolve PMIDs to PMCIDs (with caching and batching built in)
mapping = get_pmcid_from_pmid(["12895196", "17872605"])
print("=== PMID → PMCID mapping ===")
for pmid, pmcid in mapping.items():
    print(f"  PMID {pmid} → {pmcid}")
print()

# 4b. Fetch raw HTML from PubMed Central
html = get_html_from_pmcid("PMC1884285")
if html:
    print(f"=== Raw HTML length: {len(html)} characters ===\n")

# 4c. Get abstract-only markdown (for non-open-access articles)
abstract_md = get_abstract_markdown_from_pmid("12345678")
if abstract_md:
    print("=== Abstract-only markdown ===")
    print(abstract_md[:300])
    print("...\n")

# 4d. Fetch supplementary material text
supplement = fetch_bioc_supplement("PMC6435416")
if supplement:
    print("=== Supplement text ===")
    print(supplement[:300])
    print("...\n")

# ---------------------------------------------------------------------------
# 5. Command-line usage
# ---------------------------------------------------------------------------
# You can also use pubmed-markdown from the terminal:
#
#   # Convert PMIDs listed in a file (one per line)
#   pubmed-download --file_path=pmids.txt --save_dir=data
#
#   # Clear all caches
#   pubmed-download --clear_caches

print("Tutorial complete!")
