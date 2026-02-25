"""
PubMed Downloader API

Public HTTP API for converting PubMed articles (by PMID or PMCID) to markdown.
"""

import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from pubmed_downloader import PubMedDownloader

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# NCBI concurrency gate – ensures we never exceed NCBI rate limits regardless
# of how many inbound requests arrive at once.  3 req/s without an API key.
# ---------------------------------------------------------------------------
NCBI_CONCURRENCY = 3
_ncbi_semaphore: asyncio.Semaphore

# ---------------------------------------------------------------------------
# In-memory job store for batch conversions
# ---------------------------------------------------------------------------
_jobs: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ncbi_semaphore
    _ncbi_semaphore = asyncio.Semaphore(NCBI_CONCURRENCY)
    yield


app = FastAPI(
    title="PubMed Downloader API",
    description="Convert PubMed articles to clean, structured markdown via PMID or PMCID.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

# ---------------------------------------------------------------------------
# CORS – allow all origins by default; tighten in production.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "message": "Too many requests."},
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
PMID_PATTERN = re.compile(r"^\d+$")
PMCID_PATTERN = re.compile(r"^PMC\d+$")


class ConvertResult(BaseModel):
    id: str
    id_type: str
    pmcid: Optional[str] = None
    markdown: Optional[str] = None
    has_supplements: bool = False
    error: Optional[str] = None


class BatchPmidRequest(BaseModel):
    pmids: List[str] = Field(..., max_length=50)

    @field_validator("pmids")
    @classmethod
    def validate_pmids(cls, v: List[str]) -> List[str]:
        for pmid in v:
            if not PMID_PATTERN.match(pmid):
                raise ValueError(f"Invalid PMID: {pmid}")
        return v


class BatchPmcidRequest(BaseModel):
    pmcids: List[str] = Field(..., max_length=50)

    @field_validator("pmcids")
    @classmethod
    def validate_pmcids(cls, v: List[str]) -> List[str]:
        for pmcid in v:
            if not PMCID_PATTERN.match(pmcid):
                raise ValueError(f"Invalid PMCID: {pmcid}")
        return v


class JobStatus(BaseModel):
    job_id: str
    status: str  # "pending" | "running" | "completed"
    total: int = 0
    completed_count: int = 0
    results: Optional[List[ConvertResult]] = None


# ---------------------------------------------------------------------------
# Shared converter instance
# ---------------------------------------------------------------------------
_converter = PubMedDownloader()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _convert_pmid(pmid: str, include_supplements: bool = True) -> ConvertResult:
    """Run the PMID→markdown pipeline in a thread (it does blocking I/O)."""
    from pubmed_downloader.pmcid_from_pmid import get_pmcid_from_pmid
    from pubmed_downloader.html_from_pmcid import get_html_from_pmcid
    from pubmed_downloader.utils_bioc import format_supplement_as_markdown

    loop = asyncio.get_event_loop()

    async with _ncbi_semaphore:
        pmcid_mapping = await loop.run_in_executor(None, get_pmcid_from_pmid, [pmid])
    pmcid = pmcid_mapping.get(str(pmid))
    if pmcid is None:
        return ConvertResult(
            id=pmid,
            id_type="pmid",
            error="No PMCID found for this PMID. The article may not be available in PubMed Central.",
        )

    async with _ncbi_semaphore:
        html = await loop.run_in_executor(None, get_html_from_pmcid, pmcid)
    if html is None:
        return ConvertResult(
            id=pmid,
            id_type="pmid",
            pmcid=pmcid,
            error="Failed to fetch HTML from PubMed Central.",
        )

    try:
        markdown = await loop.run_in_executor(
            None, _converter.html_to_markdown.convert_html, html
        )
    except Exception as e:
        return ConvertResult(
            id=pmid,
            id_type="pmid",
            pmcid=pmcid,
            error=f"HTML to markdown conversion failed: {e}",
        )

    has_supplements = False
    if include_supplements:
        async with _ncbi_semaphore:
            supplement = await loop.run_in_executor(
                None, format_supplement_as_markdown, pmcid
            )
        if supplement:
            markdown = markdown.rstrip() + "\n\n" + supplement + "\n"
            has_supplements = True

    return ConvertResult(
        id=pmid,
        id_type="pmid",
        pmcid=pmcid,
        markdown=markdown,
        has_supplements=has_supplements,
    )


async def _convert_pmcid(pmcid: str, include_supplements: bool = True) -> ConvertResult:
    """Run the PMCID→markdown pipeline in a thread (it does blocking I/O)."""
    from pubmed_downloader.html_from_pmcid import get_html_from_pmcid
    from pubmed_downloader.utils_bioc import format_supplement_as_markdown

    loop = asyncio.get_event_loop()

    async with _ncbi_semaphore:
        html = await loop.run_in_executor(None, get_html_from_pmcid, pmcid)
    if html is None:
        return ConvertResult(
            id=pmcid,
            id_type="pmcid",
            pmcid=pmcid,
            error="Failed to fetch HTML from PubMed Central.",
        )

    try:
        markdown = await loop.run_in_executor(
            None, _converter.html_to_markdown.convert_html, html
        )
    except Exception as e:
        return ConvertResult(
            id=pmcid,
            id_type="pmcid",
            pmcid=pmcid,
            error=f"HTML to markdown conversion failed: {e}",
        )

    has_supplements = False
    if include_supplements:
        async with _ncbi_semaphore:
            supplement = await loop.run_in_executor(
                None, format_supplement_as_markdown, pmcid
            )
        if supplement:
            markdown = markdown.rstrip() + "\n\n" + supplement + "\n"
            has_supplements = True

    return ConvertResult(
        id=pmcid,
        id_type="pmcid",
        pmcid=pmcid,
        markdown=markdown,
        has_supplements=has_supplements,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/convert/pmid/{pmid}", response_model=ConvertResult)
@limiter.limit("10/minute")
async def convert_pmid(
    request: Request,
    pmid: str,
    include_supplements: bool = Query(True),
):
    """Convert a single PMID to markdown."""
    if not PMID_PATTERN.match(pmid):
        raise HTTPException(status_code=422, detail="PMID must be numeric.")
    result = await _convert_pmid(pmid, include_supplements)
    if result.error and result.markdown is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "conversion_failed",
                "message": result.error,
                "pmid": pmid,
            },
        )
    return result


@app.get("/convert/pmcid/{pmcid}", response_model=ConvertResult)
@limiter.limit("10/minute")
async def convert_pmcid(
    request: Request,
    pmcid: str,
    include_supplements: bool = Query(True),
):
    """Convert a single PMCID to markdown, skipping PMID resolution."""
    if not PMCID_PATTERN.match(pmcid):
        raise HTTPException(
            status_code=422, detail="PMCID must match pattern PMC followed by digits."
        )
    result = await _convert_pmcid(pmcid, include_supplements)
    if result.error and result.markdown is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "conversion_failed",
                "message": result.error,
                "pmcid": pmcid,
            },
        )
    return result


# ---------------------------------------------------------------------------
# Batch endpoints — return a job ID, process in background
# ---------------------------------------------------------------------------
async def _run_batch_pmid_job(job_id: str, pmids: List[str], include_supplements: bool):
    _jobs[job_id]["status"] = "running"
    results: List[ConvertResult] = []
    for pmid in pmids:
        result = await _convert_pmid(pmid, include_supplements)
        results.append(result)
        _jobs[job_id]["completed_count"] = len(results)
    _jobs[job_id]["status"] = "completed"
    _jobs[job_id]["results"] = [r.model_dump() for r in results]


async def _run_batch_pmcid_job(
    job_id: str, pmcids: List[str], include_supplements: bool
):
    _jobs[job_id]["status"] = "running"
    results: List[ConvertResult] = []
    for pmcid in pmcids:
        result = await _convert_pmcid(pmcid, include_supplements)
        results.append(result)
        _jobs[job_id]["completed_count"] = len(results)
    _jobs[job_id]["status"] = "completed"
    _jobs[job_id]["results"] = [r.model_dump() for r in results]


@app.post("/convert/pmids", response_model=JobStatus)
@limiter.limit("5/minute")
async def batch_convert_pmids(
    request: Request,
    body: BatchPmidRequest,
    include_supplements: bool = Query(True),
):
    """Submit a batch of PMIDs for conversion. Returns a job ID to poll."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "total": len(body.pmids),
        "completed_count": 0,
        "results": None,
    }
    asyncio.create_task(_run_batch_pmid_job(job_id, body.pmids, include_supplements))
    return JobStatus(job_id=job_id, status="pending", total=len(body.pmids))


@app.post("/convert/pmcids", response_model=JobStatus)
@limiter.limit("5/minute")
async def batch_convert_pmcids(
    request: Request,
    body: BatchPmcidRequest,
    include_supplements: bool = Query(True),
):
    """Submit a batch of PMCIDs for conversion. Returns a job ID to poll."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "total": len(body.pmcids),
        "completed_count": 0,
        "results": None,
    }
    asyncio.create_task(_run_batch_pmcid_job(job_id, body.pmcids, include_supplements))
    return JobStatus(job_id=job_id, status="pending", total=len(body.pmcids))


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Poll for batch job status and results."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        total=job["total"],
        completed_count=job["completed_count"],
        results=job["results"],
    )
