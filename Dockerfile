FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=builder /install /usr/local

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/data /app/output \
    && chown -R app:app /app

COPY scripts ./scripts

USER app

ENTRYPOINT ["python3", "-m", "lifting_data.cli"]
