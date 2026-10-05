FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY app.py ./
RUN pip install --no-cache-dir fastapi>=0.115 "uvicorn[standard]>=0.30" authlib>=1.3 python-multipart>=0.0.9

RUN useradd --create-home --uid 10001 mock-oidc
USER mock-oidc

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
