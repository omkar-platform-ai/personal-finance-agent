FROM python:3.11-slim

WORKDIR /app

# System dependencies for pdfplumber / pymupdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install uv --no-cache-dir

# Copy dependency spec first for layer caching
COPY pyproject.toml .
RUN uv pip install --system --no-cache -e .

# Copy source
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/samples/ ./data/samples/

# Create data directories
RUN mkdir -p /app/data/chroma_db

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]