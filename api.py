"""
PubMed Downloader API

Public HTTP API for converting PubMed articles (by PMID or PMCID) to markdown.
"""

import asyncio
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Literal, Optional, Set

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from pubmed_markdown import (
    AsyncRateGate,
    FetchResult,
    PubMedMarkdown,
    __version__,
    get_pmcid_from_pmid,
)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# Shared NCBI concurrency + pacing gate from pubmed_markdown
_ncbi_gate: AsyncRateGate = AsyncRateGate.for_ncbi()

# ---------------------------------------------------------------------------
# Bounded in-memory job store for batch conversions
# ---------------------------------------------------------------------------
MAX_STORED_JOBS = 1000
JOB_TTL_SECONDS = 3600.0
_jobs: Dict[str, dict] = {}
_background_tasks: Set[asyncio.Task] = set()


def _prune_jobs() -> None:
    """Evict expired or excess completed jobs to keep memory bounded."""
    now = time.monotonic()
    expired = [
        jid
        for jid, j in _jobs.items()
        if j.get("status") in ("completed", "failed")
        and (now - j.get("updated_at", now)) > JOB_TTL_SECONDS
    ]
    for jid in expired:
        _jobs.pop(jid, None)

    if len(_jobs) >= MAX_STORED_JOBS:
        oldest = sorted(
            (
                (j.get("updated_at", 0.0), jid)
                for jid, j in _jobs.items()
                if j.get("status") in ("completed", "failed")
            )
        )
        for _, jid in oldest[: len(_jobs) - MAX_STORED_JOBS + 1]:
            _jobs.pop(jid, None)


def _spawn_background_task(coro) -> asyncio.Task:
    """Create a background task while retaining a strong reference until completion."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ncbi_gate
    _ncbi_gate = AsyncRateGate.for_ncbi()
    yield


app = FastAPI(
    title="PubMed Downloader API",
    description="Convert PubMed articles to clean, structured markdown via PMID or PMCID.",
    version=__version__,
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


class TierErrorModel(BaseModel):
    tier: str
    code: str
    message: str
    status_code: Optional[int] = None


class ConvertResult(BaseModel):
    id: str
    id_type: str
    pmcid: Optional[str] = None
    markdown: Optional[str] = None
    source: Optional[str] = None
    has_supplements: bool = False
    is_abstract_only: bool = False
    error: Optional[str] = None
    errors: List[TierErrorModel] = Field(default_factory=list)


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
    status: str  # "pending" | "running" | "completed" | "failed"
    total: int = 0
    completed_count: int = 0
    results: Optional[List[ConvertResult]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SourceStrategy = Literal["auto", "xml_first", "html_first", "xml", "html"]


def _fetch_result_to_convert_result(
    item_id: str,
    id_type: Literal["pmid", "pmcid"],
    fetched: FetchResult,
) -> ConvertResult:
    """Convert a package FetchResult into the HTTP API ConvertResult schema."""
    tier_errors = [
        TierErrorModel(
            tier=err.tier,
            code=err.code,
            message=err.message,
            status_code=err.status_code,
        )
        for err in fetched.errors
    ]
    error_message: Optional[str] = None
    if fetched.markdown is None:
        error_message = fetched.error_summary or (
            "Failed to fetch full text from PubMed Central (JATS XML and HTML)."
        )

    return ConvertResult(
        id=item_id,
        id_type=id_type,
        pmcid=fetched.pmcid,
        markdown=fetched.markdown,
        source=fetched.source,
        has_supplements=fetched.has_supplements,
        is_abstract_only=fetched.is_abstract_only,
        error=error_message,
        errors=tier_errors,
    )


async def _convert_pmid(
    pmid: str,
    include_supplements: bool = True,
    source: SourceStrategy = "auto",
    fallback_to_abstract: bool = True,
    pre_resolved_pmcid: Optional[str] = None,
    skip_id_lookup: bool = False,
) -> ConvertResult:
    """Run the PMID->markdown pipeline using PubMedMarkdown's built-in async API."""
    converter = PubMedMarkdown(source=source, rate_gate=_ncbi_gate)
    fetched = await converter.afetch_pmid(
        pmid,
        include_supplements=include_supplements,
        fallback_to_abstract=fallback_to_abstract,
        pre_resolved_pmcid=pre_resolved_pmcid,
        skip_id_lookup=skip_id_lookup,
    )
    return _fetch_result_to_convert_result(pmid, "pmid", fetched)


async def _convert_pmcid(
    pmcid: str,
    include_supplements: bool = True,
    source: SourceStrategy = "auto",
) -> ConvertResult:
    """Run the PMCID->markdown pipeline using PubMedMarkdown's built-in async API."""
    converter = PubMedMarkdown(source=source, rate_gate=_ncbi_gate)
    fetched = await converter.afetch_pmcid(
        pmcid, include_supplements=include_supplements
    )
    return _fetch_result_to_convert_result(pmcid, "pmcid", fetched)


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
    source: SourceStrategy = Query("auto"),
    fallback_to_abstract: bool = Query(True),
):
    """Convert a single PMID to markdown."""
    if not PMID_PATTERN.match(pmid):
        raise HTTPException(status_code=422, detail="PMID must be numeric.")
    result = await _convert_pmid(
        pmid,
        include_supplements,
        source=source,
        fallback_to_abstract=fallback_to_abstract,
    )
    if result.error and result.markdown is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "conversion_failed",
                "message": result.error,
                "pmid": pmid,
                "errors": [e.model_dump() for e in result.errors],
            },
        )
    return result


@app.get("/convert/pmcid/{pmcid}", response_model=ConvertResult)
@limiter.limit("10/minute")
async def convert_pmcid(
    request: Request,
    pmcid: str,
    include_supplements: bool = Query(True),
    source: SourceStrategy = Query("auto"),
):
    """Convert a single PMCID to markdown, skipping PMID resolution."""
    if not PMCID_PATTERN.match(pmcid):
        raise HTTPException(
            status_code=422, detail="PMCID must match pattern PMC followed by digits."
        )
    result = await _convert_pmcid(pmcid, include_supplements, source=source)
    if result.error and result.markdown is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "conversion_failed",
                "message": result.error,
                "pmcid": pmcid,
                "errors": [e.model_dump() for e in result.errors],
            },
        )
    return result


# ---------------------------------------------------------------------------
# Batch endpoints — return a job ID, process in background
# ---------------------------------------------------------------------------
async def _run_batch_pmid_job(
    job_id: str,
    pmids: List[str],
    include_supplements: bool,
    source: SourceStrategy = "auto",
    fallback_to_abstract: bool = True,
):
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["updated_at"] = time.monotonic()
    try:
        converter = PubMedMarkdown(source=source, rate_gate=_ncbi_gate)
        async with _ncbi_gate:
            pmcid_mapping = await asyncio.to_thread(
                get_pmcid_from_pmid, pmids, converter.email
            )

        results: List[ConvertResult] = []
        for pmid in pmids:
            result = await _convert_pmid(
                pmid,
                include_supplements,
                source=source,
                fallback_to_abstract=fallback_to_abstract,
                pre_resolved_pmcid=pmcid_mapping.get(str(pmid)),
                skip_id_lookup=True,
            )
            results.append(result)
            _jobs[job_id]["completed_count"] = len(results)
            _jobs[job_id]["updated_at"] = time.monotonic()

        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["results"] = [r.model_dump() for r in results]
    except Exception as e:
        logger.exception(f"Batch PMID job {job_id} failed: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
    finally:
        _jobs[job_id]["updated_at"] = time.monotonic()


async def _run_batch_pmcid_job(
    job_id: str,
    pmcids: List[str],
    include_supplements: bool,
    source: SourceStrategy = "auto",
):
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["updated_at"] = time.monotonic()
    try:
        results: List[ConvertResult] = []
        for pmcid in pmcids:
            result = await _convert_pmcid(pmcid, include_supplements, source=source)
            results.append(result)
            _jobs[job_id]["completed_count"] = len(results)
            _jobs[job_id]["updated_at"] = time.monotonic()
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["results"] = [r.model_dump() for r in results]
    except Exception as e:
        logger.exception(f"Batch PMCID job {job_id} failed: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
    finally:
        _jobs[job_id]["updated_at"] = time.monotonic()


@app.post("/convert/pmids", response_model=JobStatus)
@limiter.limit("5/minute")
async def batch_convert_pmids(
    request: Request,
    body: BatchPmidRequest,
    include_supplements: bool = Query(True),
    source: SourceStrategy = Query("auto"),
    fallback_to_abstract: bool = Query(True),
):
    """Submit a batch of PMIDs for conversion. Returns a job ID to poll."""
    _prune_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "total": len(body.pmids),
        "completed_count": 0,
        "results": None,
        "error": None,
        "updated_at": time.monotonic(),
    }
    _spawn_background_task(
        _run_batch_pmid_job(
            job_id,
            body.pmids,
            include_supplements,
            source=source,
            fallback_to_abstract=fallback_to_abstract,
        )
    )
    return JobStatus(job_id=job_id, status="pending", total=len(body.pmids))


@app.post("/convert/pmcids", response_model=JobStatus)
@limiter.limit("5/minute")
async def batch_convert_pmcids(
    request: Request,
    body: BatchPmcidRequest,
    include_supplements: bool = Query(True),
    source: SourceStrategy = Query("auto"),
):
    """Submit a batch of PMCIDs for conversion. Returns a job ID to poll."""
    _prune_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "total": len(body.pmcids),
        "completed_count": 0,
        "results": None,
        "error": None,
        "updated_at": time.monotonic(),
    }
    _spawn_background_task(
        _run_batch_pmcid_job(job_id, body.pmcids, include_supplements, source=source)
    )
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
        error=job.get("error"),
    )
