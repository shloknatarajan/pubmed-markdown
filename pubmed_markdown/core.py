from .pmcid_from_pmid import get_pmcid_from_pmid
from .html_from_pmcid import get_html_from_pmcid
from .markdown_from_html import PubMedHTMLToMarkdownConverter
from .utils_bioc import format_supplement_as_markdown
from .abstract_from_pmid import get_abstract_markdown_from_pmid
from typing import List, Optional, Union
import os
from loguru import logger
from tqdm import tqdm
import argparse
import time


class PubMedMarkdown:
    """
    Args:
        save_dir (str): Directory to save the files to (default: "data/")
        email (str, optional): Email for NCBI API identification. Falls back to NCBI_EMAIL env var.
        ncbi_key (str, optional): NCBI API key for E-utilities (increases rate limit from 3 to 10 req/s).
            Falls back to NCBI_API_KEY env var.
        request_delay (float, optional): Minimum delay in seconds between consecutive PMC requests
            in batch operations (default: 0.5).
    """

    def __init__(
        self,
        save_dir: str = "data",
        email: Optional[str] = None,
        ncbi_key: Optional[str] = None,
        request_delay: Optional[float] = None,
    ):
        self.html_to_markdown = PubMedHTMLToMarkdownConverter()
        self.save_dir = save_dir
        self.email = email or os.getenv("NCBI_EMAIL")
        self.ncbi_key = ncbi_key or os.getenv("NCBI_API_KEY")
        self.request_delay = 0.5 if request_delay is None else request_delay
        if not self.email:
            logger.warning(
                "No NCBI email configured. Set NCBI_EMAIL environment variable "
                "or pass email to PubMedMarkdown(). NCBI may block requests (403)."
            )

    @property
    def _eutils_delay(self) -> float:
        """Delay between consecutive NCBI E-utilities calls (~10 req/s with key, ~3 req/s without)."""
        return 0.15 if self.ncbi_key else 0.4

    def _single_pmcid_to_markdown(
        self, pmcid: str, include_supplements: bool = True
    ) -> Optional[str]:
        """Convert a single PMCID to markdown. Internal helper."""
        html = get_html_from_pmcid(pmcid, email=self.email)
        if html is None:
            return None

        try:
            markdown = self.html_to_markdown.convert_html(html)
        except Exception as e:
            logger.error(
                f"Error converting HTML to markdown for PMCID {pmcid}: {str(e)}"
            )
            return None

        if include_supplements:
            supplement = format_supplement_as_markdown(pmcid)
            if supplement:
                markdown = markdown.rstrip() + "\n\n" + supplement + "\n"

        return markdown

    def pmcid_to_markdown(
        self,
        pmcids: Union[str, List[str]],
        include_supplements: bool = True,
    ) -> Union[Optional[str], List[Optional[str]]]:
        """
        Convert one or more PMCIDs directly to markdown, skipping PMID resolution.

        Args:
            pmcids (str or List[str]): A single PMCID or list of PMCIDs (e.g. "PMC1234567")
            include_supplements (bool): Whether to append supplementary materials (default: True)

        Returns:
            If a single PMCID string was passed: Optional[str] — the markdown or None.
            If a list was passed: List[Optional[str]] — one result per input PMCID.
        """
        if isinstance(pmcids, str):
            return self._single_pmcid_to_markdown(pmcids, include_supplements)

        results: List[Optional[str]] = []
        for idx, pmcid in enumerate(tqdm(pmcids, desc="Converting PMCIDs to markdown")):
            if idx > 0 and self.request_delay > 0:
                time.sleep(self.request_delay)
            results.append(self._single_pmcid_to_markdown(pmcid, include_supplements))
        return results

    def _single_pmid_to_markdown(
        self, pmid: str, include_supplements: bool = True
    ) -> Optional[str]:
        """Convert a single PMID to markdown. Internal helper."""
        pmcid_mapping = get_pmcid_from_pmid([pmid], email=self.email)
        pmcid = pmcid_mapping.get(str(pmid).strip())

        if pmcid is None:
            logger.warning(
                f"PMID {pmid} is not available on PubMed Central (Open Access). "
                f"Downloading abstract only."
            )
            return get_abstract_markdown_from_pmid(
                pmid, email=self.email, ncbi_key=self.ncbi_key
            )

        return self._single_pmcid_to_markdown(pmcid, include_supplements)

    def pmid_to_markdown(
        self,
        pmid: Union[str, List[str]],
        include_supplements: bool = True,
    ) -> Union[Optional[str], List[Optional[str]]]:
        """
        Convert one or more PMIDs to markdown (returned as strings, not saved to disk).
        Falls back to abstract-only if no PMCID is available.

        Args:
            pmid (str or List[str]): A single PMID or list of PMIDs
            include_supplements (bool): Whether to append supplementary materials (default: True)

        Returns:
            If a single PMID string was passed: Optional[str] — the markdown or None.
            If a list was passed: List[Optional[str]] — one result per input PMID.
        """
        if isinstance(pmid, str):
            return self._single_pmid_to_markdown(pmid, include_supplements)

        normalized_pmids = [str(p).strip() for p in pmid]
        pmcid_mapping = get_pmcid_from_pmid(normalized_pmids, email=self.email)

        results: List[Optional[str]] = []
        for idx, p in enumerate(
            tqdm(normalized_pmids, desc="Converting PMIDs to markdown")
        ):
            pmcid = pmcid_mapping.get(p)
            if idx > 0:
                delay = self.request_delay if pmcid is not None else self._eutils_delay
                if delay > 0:
                    time.sleep(delay)

            if pmcid is None:
                logger.warning(
                    f"PMID {p} is not available on PubMed Central (Open Access). "
                    f"Downloading abstract only."
                )
                results.append(
                    get_abstract_markdown_from_pmid(
                        p, email=self.email, ncbi_key=self.ncbi_key
                    )
                )
            else:
                results.append(
                    self._single_pmcid_to_markdown(pmcid, include_supplements)
                )

        return results

    def check_existing_html_pmcids(self, save_dir: str = "data/") -> List[str]:
        """
        Get a list of all PMCIDs that have HTML files in the save_dir/html directory.

        Args:
            save_dir (str): Directory to check for HTML files (default: "data/")

        Returns:
            List[str]: List of PMCIDs that have existing HTML files
        """
        html_dir = os.path.join(save_dir, "html")
        if not os.path.exists(html_dir):
            return []

        existing_html = []
        for filename in os.listdir(html_dir):
            if filename.endswith(".html"):
                pmcid = filename[:-5]  # Remove .html extension
                existing_html.append(pmcid)
        return existing_html

    def check_existing_markdown_pmcids(self, save_dir: str = "data/") -> List[str]:
        """
        Get a list of all PMCIDs that have markdown files in the save_dir/markdown directory.

        Args:
            save_dir (str): Directory to check for markdown files (default: "data/")

        Returns:
            List[str]: List of PMCIDs that have existing markdown files
        """
        markdown_dir = os.path.join(save_dir, "markdown")
        if not os.path.exists(markdown_dir):
            return []

        existing_markdown = []
        for filename in os.listdir(markdown_dir):
            if filename.endswith(".md"):
                pmcid = filename[:-3]  # Remove .md extension
                existing_markdown.append(pmcid)
        return existing_markdown

    def local_html_to_markdown(
        self, save_dir: str = "data/", overwrite: bool = False
    ) -> None:
        """
        Convert all html files in the save_dir/html directory to markdown

        Args:
            save_dir (str): Directory containing HTML files (default: "data/")
            overwrite (bool): Whether to overwrite existing markdown files (default: False)
        """
        html_dir = os.path.join(save_dir, "html")
        if not os.path.exists(html_dir):
            logger.warning(f"No HTML directory found at {html_dir}")
            return

        htmls = os.listdir(html_dir)
        html_paths = [os.path.join(html_dir, f) for f in htmls]

        if not overwrite:
            # Get existing markdown files
            existing_markdown = self.check_existing_markdown_pmcids(save_dir)
            logger.info(f"Found {len(existing_markdown)} existing markdown files")
            # Filter out HTML files that already have markdown
            htmls = [
                html
                for html in htmls
                if html.replace(".html", "") not in existing_markdown
            ]
            html_paths = [os.path.join(html_dir, f) for f in htmls]

        logger.info(f"Converting {len(htmls)} HTML files to Markdown")
        for html_path in tqdm(
            html_paths, desc=f"Converting html ({save_dir}/html) to markdown"
        ):
            try:
                markdown = self.html_to_markdown.convert_file(html_path)
            except Exception as e:
                logger.error(f"Skipping {html_path}: {e}")
                continue

            # Append supplementary materials
            pmcid = os.path.basename(html_path).replace(".html", "")
            supplement = format_supplement_as_markdown(pmcid)
            if supplement:
                markdown = markdown.rstrip() + "\n\n" + supplement + "\n"
            else:
                markdown = (
                    markdown.rstrip()
                    + "\n\n## Supplementary Materials\n\nNo supplementary materials found.\n"
                )

            md_path = os.path.join(
                save_dir,
                "markdown",
                f"{os.path.basename(html_path).replace('.html', '.md')}",
            )
            with open(md_path, "w") as f:
                f.write(markdown)

    def pmids_to_pmcids(
        self, pmids: Union[str, List[str]], save_dir: str = "data"
    ) -> List[str]:
        """
        Convert one or more PMIDs to PMCIDs.

        Args:
            pmids (str or List[str]): A single PMID or list of PMIDs
            save_dir (str): Directory for output (default: "data")
        """
        if isinstance(pmids, str):
            pmids = [pmids]
        pmids = [str(p).strip() for p in pmids]
        total = len(pmids)
        logger.info(f"Getting PMCIDs for {total} PMIDs")
        pmcid_mapping = get_pmcid_from_pmid(pmids, email=self.email)
        # Lookup using normalized keys
        pmcids = [pmcid_mapping.get(str(pmid).strip()) for pmid in pmids]
        valid_pmcids = [pmcid for pmcid in pmcids if pmcid is not None]
        missing = total - len(valid_pmcids)
        sample = ", ".join([str(p) for p in valid_pmcids[:5]]) if valid_pmcids else ""
        # Diagnostics when results look off
        if len(valid_pmcids) == 0:
            logger.warning(
                f"No valid PMCIDs found. Debug: mapping_keys={len(pmcid_mapping.keys())}"
            )
            # Show up to 5 sample lookups
            for pmid in pmids[:5]:
                key = str(pmid).strip()
                logger.debug(
                    f"Lookup sample: PMID {key} -> {pmcid_mapping.get(key)} (in_mapping={key in pmcid_mapping})"
                )
        logger.info(f"Valid PMCIDs: {len(valid_pmcids)} / {total} | Missing: {missing}")
        if sample:
            logger.debug(f"Sample PMCIDs: {sample}...")
        return valid_pmcids

    def pmcids_to_html(
        self, pmcids: Union[str, List[str]], save_dir: str = "data"
    ) -> None:
        """
        Convert one or more PMCIDs to HTML and save to disk.

        Args:
            pmcids (str or List[str]): A single PMCID or list of PMCIDs
            save_dir (str): Directory to save the files to (default: "data/")
        """
        if isinstance(pmcids, str):
            pmcids = [pmcids]
        # Create necessary directories
        html_dir = os.path.join(save_dir, "html")
        markdown_dir = os.path.join(save_dir, "markdown")
        os.makedirs(html_dir, exist_ok=True)
        os.makedirs(markdown_dir, exist_ok=True)

        # Get existing HTML files
        existing_html = self.check_existing_html_pmcids(save_dir)
        logger.info(f"Found {len(existing_html)} existing html files")
        # Filter out PMCIDs that already have HTML
        pmcids = [pmcid for pmcid in pmcids if pmcid not in existing_html]
        logger.info(f"Converting {len(pmcids)} PMCIDs to HTML")

        # Convert to HTML
        for idx, pmcid in enumerate(tqdm(pmcids, desc="Converting PMCIDs to HTML")):
            if idx > 0 and self.request_delay > 0:
                time.sleep(self.request_delay)
            html_text = get_html_from_pmcid(pmcid, email=self.email)
            if html_text is None:
                logger.error(f"No HTML found for PMCID {pmcid}")
                continue

            # Save HTML
            try:
                html_path = os.path.join(html_dir, f"{pmcid}.html")
                with open(html_path, "w") as f:
                    f.write(html_text)
            except Exception as e:
                logger.error(f"Error saving HTML for PMCID {pmcid}: {str(e)}")
                continue

    def pmids_to_markdown_files(
        self,
        pmids: Union[str, List[str]],
        save_dir: str = "data",
        overwrite: bool = False,
    ) -> None:
        """
        Convert one or more PMIDs to markdown and save to disk.

        Args:
            pmids (str or List[str]): A single PMID or list of PMIDs to convert
            save_dir (str): Directory to save the files to (default: "data/")
            overwrite (bool): Whether to overwrite existing files (default: False)
        """
        # Normalize to list
        if isinstance(pmids, str):
            pmids = [pmids]
        pmids = [str(p).strip() for p in pmids]

        # Ensure save_dir exists before any writes
        os.makedirs(save_dir, exist_ok=True)

        # Get PMCID mapping for all PMIDs
        pmcid_mapping = get_pmcid_from_pmid(pmids, email=self.email)

        # Split into PMIDs with and without PMCIDs
        pmids_with_pmcid = []
        pmids_without_pmcid = []
        for pmid in pmids:
            pmcid = pmcid_mapping.get(pmid)
            if pmcid:
                pmids_with_pmcid.append((pmid, pmcid))
            else:
                pmids_without_pmcid.append(pmid)

        valid_pmcids = [pmcid for _, pmcid in pmids_with_pmcid]

        if not overwrite:
            existing_markdown = self.check_existing_markdown_pmcids(save_dir)
            logger.info(f"Found {len(existing_markdown)} existing markdown files")
            valid_pmcids = [
                pmcid for pmcid in valid_pmcids if pmcid not in existing_markdown
            ]
            pmids_without_pmcid = [
                pmid
                for pmid in pmids_without_pmcid
                if f"PMID{pmid}" not in existing_markdown
            ]

        # Full-text path: PMCIDs -> HTML -> Markdown
        logger.info(f"Converting {len(valid_pmcids)} PMCIDs to Markdown (full text)")
        self.pmcids_to_html(valid_pmcids, save_dir)
        self.local_html_to_markdown(save_dir, overwrite=overwrite)

        # Abstract fallback for PMIDs without PMCIDs
        if pmids_without_pmcid:
            logger.info(
                f"{len(pmids_without_pmcid)} PMIDs have no PMCID (not open access). "
                f"Fetching abstracts only."
            )
            markdown_dir = os.path.join(save_dir, "markdown")
            os.makedirs(markdown_dir, exist_ok=True)

            for idx, pmid in enumerate(
                tqdm(pmids_without_pmcid, desc="Fetching abstracts for non-OA articles")
            ):
                if idx > 0 and self._eutils_delay > 0:
                    time.sleep(self._eutils_delay)
                logger.warning(
                    f"PMID {pmid} is not available on PubMed Central (Open Access). "
                    f"Downloading abstract only."
                )
                markdown = get_abstract_markdown_from_pmid(
                    pmid, email=self.email, ncbi_key=self.ncbi_key
                )
                if markdown is None:
                    logger.error(f"Failed to fetch abstract for PMID {pmid}")
                    continue

                markdown = (
                    markdown.rstrip()
                    + "\n\n## Supplementary Materials\n\nNo supplementary materials found.\n"
                )

                md_path = os.path.join(markdown_dir, f"PMID{pmid}.md")
                with open(md_path, "w") as f:
                    f.write(markdown)


def convert_pmids_from_file(
    file_path: str,
    save_dir: str = "data",
    overwrite: bool = False,
    email: Optional[str] = None,
    ncbi_key: Optional[str] = None,
):
    """
    Convert pmids from a txt file to markdown
    Expects a txt file with one PMID per line

    Args:
        file_path (str): Path to the txt file containing PMIDs
        save_dir (str): Directory to save the files to (default: "data/")
        overwrite (bool): Whether to overwrite existing markdown files (default: False)
        email (str, optional): Email for NCBI API identification.
        ncbi_key (str, optional): NCBI API key for higher E-utilities rate limits.
    """
    converter = PubMedMarkdown(email=email, ncbi_key=ncbi_key)
    pmids = [line.strip() for line in open(file_path, "r").readlines() if line.strip()]
    converter.pmids_to_markdown_files(pmids, save_dir, overwrite)


def main():
    """CLI entry point for pubmed-download."""
    parser = argparse.ArgumentParser(description="Convert PMIDs to markdown format")
    parser.add_argument(
        "--file_path", type=str, help="Path to the txt file containing PMIDs"
    )
    parser.add_argument(
        "--save_dir",
        type=str,
        default="data",
        help="Directory to save the files to (default: 'data/')",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Whether to overwrite existing markdown files (default: False)",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Email for NCBI API identification (overrides NCBI_EMAIL env var)",
    )
    parser.add_argument(
        "--ncbi_key",
        type=str,
        default=None,
        help="NCBI API key for E-utilities (overrides NCBI_API_KEY env var)",
    )
    args = parser.parse_args()

    if args.file_path:
        convert_pmids_from_file(
            args.file_path,
            args.save_dir,
            args.overwrite,
            email=args.email,
            ncbi_key=args.ncbi_key,
        )
    else:
        parser.error("--file_path is required")


if __name__ == "__main__":
    main()
