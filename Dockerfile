FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY content_pipeline ./content_pipeline
COPY profiles ./profiles
COPY app.py ./

RUN pip install --no-cache-dir .

ENV PIPELINE_DATA_DIR=/data
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
