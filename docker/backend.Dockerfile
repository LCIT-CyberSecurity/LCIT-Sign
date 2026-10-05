FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker/entrypoint.sh ./entrypoint.sh
RUN pip install --no-cache-dir '.' && chmod +x ./entrypoint.sh

RUN useradd --create-home --uid 10001 lcit-sign \
    && mkdir -p /var/lib/lcit-sign \
    && chown -R lcit-sign:lcit-sign /app /var/lib/lcit-sign
USER lcit-sign

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["./entrypoint.sh"]
