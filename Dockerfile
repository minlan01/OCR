# =====================================================
# Stage 1: Builder
# =====================================================
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# =====================================================
# Stage 2: Runtime
# =====================================================
FROM python:3.12-slim

LABEL app="ScanStruct API"
LABEL version="0.1.0"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV APP_ENV=production
ENV PYTHONPATH="/app:/usr/local/lib/python3.12/site-packages"
ENV PATH="/usr/local/lib/python3.12/site-packages/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0t64 \
    libgomp1 \
    fonts-noto-cjk \
    fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r scanstruct -g 10000 \
    && useradd -r -u 10000 -g scanstruct -d /app -s /sbin/nologin scanstruct

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.12/site-packages

COPY --chown=scanstruct:scanstruct . .

RUN mkdir -p /app/scan_input /app/scan_error /app/scan_archive \
    && chown -R scanstruct:scanstruct /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8900/api/v1/health')" || exit 1

USER scanstruct

EXPOSE 8900

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8900"]
