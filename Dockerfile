FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pydantic \
    boto3 \
    httpx

ENV PYTHONPATH=/app \
    MIDAS_OFFLINE_MODE=1 \
    MIDAS_WORKLOADS_DIR=/app/workloads
