FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 DEBIAN_FRONTEND=noninteractive

# LibreOffice's text-document part only (no Impress, Calc, Base, Java, no recommended extras).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer libreoffice-core \
       fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py ./
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "python-multipart>=0.0.9"

RUN useradd --create-home --uid 10002 converter
USER converter

EXPOSE 8090
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
