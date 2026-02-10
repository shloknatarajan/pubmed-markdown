# PubMed Downloader — Public API Endpoint Plan

## Goal

Expose the PubMedDownloader pipeline as a publicly available HTTP API with two core endpoints:

- **PMID → Markdown** (resolves PMID → PMCID → HTML → markdown)
- **PMCID → Markdown** (skips PMID resolution, goes directly HTML → markdown)

This is important because not every PMID maps to a freely available PMC article. Offering the PMCID endpoint lets callers who already know their PMCID skip the resolution step entirely.

---

## Phase 1: Core API

### 1.1 Add a `single_pmcid_to_markdown` method

The existing `PubMedDownloader` has `single_pmid_to_markdown` but no equivalent that accepts a PMCID directly. Add:

```python
def single_pmcid_to_markdown(self, pmcid: str) -> Optional[str]:
    html = get_html_from_pmcid(pmcid)
    if html is None:
        return None
    markdown = self.html_to_markdown.convert_html(html)
    supplement = format_supplement_as_markdown(pmcid)
    if supplement:
        markdown = markdown.rstrip() + "\n\n" + supplement + "\n"
    return markdown
```

### 1.2 Create the FastAPI application

Add `api.py` at the project root (or `src/api.py`). Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/convert/pmid/{pmid}` | Convert a single PMID to markdown |
| `GET` | `/convert/pmcid/{pmcid}` | Convert a single PMCID to markdown |
| `POST` | `/convert/pmids` | Batch convert PMIDs (async job) |
| `POST` | `/convert/pmcids` | Batch convert PMCIDs (async job) |
| `GET` | `/health` | Health check |

**Single-article responses** return immediately:

```json
{
  "id": "12895196",
  "id_type": "pmid",
  "pmcid": "PMC1234567",
  "markdown": "# Article Title\n...",
  "has_supplements": true
}
```

If conversion fails (no PMC article, HTML fetch error, etc.), return a `404` or `422` with a clear error message.

**Batch responses** return a job ID. Callers poll a `/jobs/{job_id}` endpoint to retrieve results. This avoids long-lived HTTP connections when converting dozens of articles.

### 1.3 Query parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `include_supplements` | `true` | Whether to fetch and append supplementary materials |

---

## Phase 2: Rate Limiting and Caching

### 2.1 Rate limiting

NCBI allows 3 requests/sec without an API key, 10/sec with one. The API must enforce this internally regardless of how many concurrent users hit it.

- Use an async semaphore or token-bucket to gate outbound NCBI calls.
- Apply per-client rate limiting on inbound requests (e.g., `slowapi` with IP-based keys) to prevent abuse.
- Return `429 Too Many Requests` when limits are exceeded.

### 2.2 Caching

The current file-based cache (`data/cache/pmid_to_pmcid.json`) won't work in a multi-worker deployment. Options (in order of simplicity):

1. **SQLite** — good enough for a single-server deployment. Zero infrastructure overhead.
2. **Redis** — standard choice for multi-worker deployments. Supports TTLs natively.

Cache layers:
- **PMID → PMCID mapping** (long TTL, rarely changes)
- **Converted markdown** (cache the final output keyed by PMCID, with a configurable TTL)

### 2.3 NCBI API key

Register for an NCBI API key and pass it via environment variable (`NCBI_API_KEY`). This raises the rate limit from 3 → 10 requests/sec.

---

## Phase 3: Deployment Infrastructure

### 3.1 Dockerfile

The current Pixi environment only targets `osx-arm64`. A Docker image needs to target Linux. Use a standard Python base image and install dependencies via pip (a `pyproject.toml` or `requirements.txt` is needed).

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY api.py .
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3.2 requirements.txt (API-specific additions)

Beyond existing dependencies, the API needs:

```
fastapi>=0.110
uvicorn[standard]>=0.29
slowapi>=0.1.9
```

### 3.3 Hosting options

| Option | Pros | Cons |
|--------|------|------|
| **Railway / Render / Fly.io** | Simple container deploy, free tiers available | Limited free-tier resources |
| **GCP Cloud Run** | Scales to zero, pay-per-request | Cold starts add latency |
| **EC2 / GCE VM** | Full control, persistent process | Manual ops, always-on cost |

Recommendation: Start with **Railway or Render** for simplicity. Move to Cloud Run if you need scale-to-zero.

### 3.4 Domain and HTTPS

Any of the hosting options above provide HTTPS by default. If you want a custom domain (e.g., `api.pubmeddownloader.com`), point a CNAME at the hosting provider.

---

## Phase 4: Hardening for Public Use

### 4.1 Authentication

Decide on access model:

- **Open with rate limits** — simplest, but vulnerable to abuse.
- **API key required** — issue keys via a simple admin flow. This is the recommended minimum for a public API.

### 4.2 Input validation

- Validate that PMIDs are numeric strings.
- Validate that PMCIDs match the pattern `PMC\d+`.
- Cap batch sizes (e.g., max 50 per request).

### 4.3 Error handling

Return structured errors:

```json
{
  "error": "pmcid_not_found",
  "message": "No PMC article found for PMID 99999999",
  "pmid": "99999999"
}
```

### 4.4 Logging and monitoring

- Structured JSON logs (loguru already supports this).
- Track request counts, latency, error rates.
- Alert on elevated error rates (could indicate NCBI is down or rate-limiting you).

### 4.5 CORS

If the API will be called from browser-based clients, configure CORS headers via FastAPI middleware.

---

## Phase 5: Documentation

### 5.1 Auto-generated docs

FastAPI provides Swagger UI (`/docs`) and ReDoc (`/redoc`) out of the box. Add descriptions and examples to the Pydantic models and route docstrings.

### 5.2 Usage examples

Provide curl and Python `requests` examples:

```bash
# Single PMID
curl https://your-api.com/convert/pmid/12895196

# Single PMCID (skip resolution)
curl https://your-api.com/convert/pmcid/PMC1234567

# Batch
curl -X POST https://your-api.com/convert/pmids \
  -H "Content-Type: application/json" \
  -d '{"pmids": ["12895196", "17872605"]}'
```

---

## Summary of New Files

| File | Purpose |
|------|---------|
| `api.py` | FastAPI application with endpoints |
| `requirements.txt` | Pip-compatible dependency list |
| `Dockerfile` | Container build for Linux deployment |
| `.env.example` | Document required env vars (`NCBI_EMAIL`, `NCBI_API_KEY`) |

## Changes to Existing Files

| File | Change |
|------|--------|
| `src/pubmed_downloader.py` | Add `single_pmcid_to_markdown()` method |
| `pixi.toml` | Add `fastapi`, `uvicorn`, `slowapi` dependencies and a `run-api` task |
