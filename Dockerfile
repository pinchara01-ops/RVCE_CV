# Backend container for the quick search / indexing API.
#
# ffmpeg and ffprobe are the reason this is a container rather than a
# serverless function: every request cuts, transcodes, or samples video.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only the API dependencies. The heavy local-model requirements
# (requirements-processing.txt) are not needed for the API-based path.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir google-genai "uvicorn[standard]"

COPY processing_indexing ./processing_indexing
COPY query_retrieval ./query_retrieval

ENV PYTHONUNBUFFERED=1 \
    QUERY_LOW_MEMORY_MODE=1 \
    PORT=8000

EXPOSE 8000

# Long uploads and multi-chunk scans need a generous keep-alive; the default
# 5s idle timeout drops connections mid-analysis.
CMD ["sh", "-c", "uvicorn processing_indexing.debug_api:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 120"]
