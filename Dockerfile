FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra api --no-install-project

COPY pubmed_markdown/ pubmed_markdown/
COPY api.py .
RUN uv sync --frozen --no-dev --extra api

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
