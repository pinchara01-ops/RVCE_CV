# One Railway/Cloud Run image for the Vite frontend and FastAPI search service.
#
# ffmpeg and ffprobe are the reason this is a container rather than a
# serverless function: every request cuts, transcodes, or samples video.
FROM node:22-slim AS frontend

WORKDIR /frontend
COPY video_search_frontend/package.json video_search_frontend/package-lock.json ./
RUN npm ci
COPY video_search_frontend ./

ARG PUBLIC_SITE_URL=https://aperturevideo.up.railway.app
ARG VITE_PUBLIC_UPLOADS_ENABLED=true
ARG VITE_GA_MEASUREMENT_ID=G-BK81TVPF9E
ENV VITE_SITE_URL=${PUBLIC_SITE_URL} \
    VITE_SEARCH_API_URL="" \
    VITE_PUBLIC_UPLOADS_ENABLED=${VITE_PUBLIC_UPLOADS_ENABLED} \
    VITE_GA_MEASUREMENT_ID=${VITE_GA_MEASUREMENT_ID}
RUN npm run build

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only the API dependencies. The heavy local-model requirements
# (requirements-processing.txt) are not needed for the API-based path.
COPY requirements-cloudrun.txt ./
RUN pip install --no-cache-dir -r requirements-cloudrun.txt

COPY processing_indexing ./processing_indexing
COPY query_retrieval ./query_retrieval
COPY test_assets/media/public_demo ./test_assets/media/public_demo
RUN if [ ! -f test_assets/media/public_demo/animal_belly_rub.webm ]; then \
        curl --fail --location --retry 3 \
        --output test_assets/media/public_demo/animal_belly_rub.webm \
        "https://commons.wikimedia.org/wiki/Special:Redirect/file/Adorable_Animals_Enjoying_A_Belly_Rub_Compilation_2014_NEW.webm"; \
    fi \
    && if [ ! -f test_assets/media/public_demo/barking_dog_reaction.webm ]; then \
        curl --fail --location --retry 3 \
        --output test_assets/media/public_demo/barking_dog_reaction.webm \
        "https://commons.wikimedia.org/wiki/Special:Redirect/file/Barking_Dog_Reaction.webm"; \
    fi
COPY --from=frontend /frontend/dist ./video_search_frontend/dist

ENV PYTHONUNBUFFERED=1 \
    QUERY_LOW_MEMORY_MODE=1 \
    PORT=8000

EXPOSE 8000

# Railway and Cloud Run inject PORT. One process serves both the SPA and API.
CMD ["sh", "-c", "uvicorn processing_indexing.debug_api:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 120"]
