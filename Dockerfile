FROM python:3.11-slim

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy application metadata and source before installing the package.
COPY pyproject.toml ./
COPY src ./src
COPY profiles ./profiles
COPY app.py ./

# Install dependencies and the src-layout package.
RUN pip install --no-cache-dir .

# Switch to non-root
USER appuser

ENV PIPELINE_DATA_DIR=/data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
