FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS development

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

EXPOSE 8000

CMD ["uvicorn", "repolens_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--app-dir", "src"]

FROM development AS worker-development

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

USER 65534:65534

CMD ["celery", "--app", "repolens_api.celery_app:celery_app", "worker", "--loglevel", "info", "--concurrency", "2"]
