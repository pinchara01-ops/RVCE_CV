# Deploy Aperture as one hosted container

Aperture ships as one container. The Docker build compiles the Vite frontend,
then copies it into the FastAPI image. FastAPI serves the website, API, sample
media, uploads, generated clips, and SPA route fallbacks from one origin.

Recommended public URL: `https://aperture.uleft.site`.

## 1. Local production-like run

Build the frontend, then start the unified service from the repository root:

```powershell
Set-Location video_search_frontend
$env:VITE_SITE_URL='http://localhost:8080'
npm ci
npm run build
Set-Location ..
$env:PORT='8080'
python -m uvicorn processing_indexing.debug_api:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`. Requests under `/api` stay API requests; all
other application routes fall back to the compiled `index.html`.

## 2. Railway

Create a Railway project from this repository and select the
`product-hunt-launch` branch. Railway detects the root `Dockerfile`; the
checked-in `railway.json` configures `/api/health` as the deployment health
check.

Generate a public domain, then add these service variables in Railway:

```text
GEMINI_API_KEYS_JSON=["first-key","second-key"]
PUBLIC_LAUNCH_MODE=true
PUBLIC_UPLOADS_ENABLED=true
PUBLIC_DEMO_MAX_VIDEO_BYTES=26214400
VISITOR_COOKIE_SECRET=<independent random value, at least 32 bytes>
IP_HASH_SECRET=<different random value, at least 32 bytes>
UPSTASH_REDIS_REST_URL=<server-only Upstash REST URL>
UPSTASH_REDIS_REST_TOKEN=<server-only Upstash REST token>
ALLOWED_ORIGINS=https://<generated Railway domain>
```

Do not add the key pool to a `VITE_*` variable. The backend parses the JSON
array once, cycles keys round-robin, and advances to the next key on bounded
quota or transient retries. A key pool is operational failover, not a way to
bypass provider project/account limits.

Railway injects `PORT`; do not define it manually. Keep one replica initially
because uploads and generated clips use the instance's temporary filesystem.
After deployment, verify:

```bash
curl https://YOUR_RAILWAY_DOMAIN/api/health
curl https://YOUR_RAILWAY_DOMAIN/api/public/samples
```

The repository contains sample media in the image. Personal uploads are
temporary and can disappear when Railway restarts or redeploys the service.

## 3. Google Cloud prerequisites

Select the project and enable the required services:

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

Create independent secrets in Secret Manager through the Google Cloud console:

- `aperture-gemini-api-key`
- `aperture-visitor-cookie-secret`
- `aperture-ip-hash-secret`
- `aperture-upstash-url`
- `aperture-upstash-token`

Secret values must never be passed in shell history or committed files.

## 4. Deploy to Cloud Run

From the repository root:

```bash
gcloud run deploy aperture \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --concurrency 4 \
  --timeout 900 \
  --min-instances 1 \
  --max-instances 4 \
  --set-env-vars PUBLIC_LAUNCH_MODE=true,PUBLIC_UPLOADS_ENABLED=true,PUBLIC_DEMO_MAX_VIDEO_BYTES=26214400 \
  --set-secrets GEMINI_API_KEY=aperture-gemini-api-key:latest,VISITOR_COOKIE_SECRET=aperture-visitor-cookie-secret:latest,IP_HASH_SECRET=aperture-ip-hash-secret:latest,UPSTASH_REDIS_REST_URL=aperture-upstash-url:latest,UPSTASH_REDIS_REST_TOKEN=aperture-upstash-token:latest
```

The image already contains the two approved public samples and ffmpeg. The
sample path environment variables are optional overrides.

The hosted image installs `requirements-cloudrun.txt`. Heavy local-model
packages remain available through the existing self-hosted requirements but
are deliberately excluded from the Gemini-based public image.

## 5. Domain

Because the owned domain is `uleft.site`, use `aperture.uleft.site`. The name
`uleft.aperture.site` would require control of `aperture.site`.

For launch traffic, put a global external Application Load Balancer with a
serverless NEG in front of the Cloud Run service, attach a Google-managed TLS
certificate for `aperture.uleft.site`, and add the DNS record Google provides.
This keeps the frontend and API same-origin and preserves the secure visitor
cookie. Direct Cloud Run domain mapping can be used where supported, but the
load balancer is the stronger production configuration.

After the custom domain is active, set:

```text
ALLOWED_ORIGINS=https://aperture.uleft.site
```

The frontend uses same-origin API URLs in production, so no separate frontend
API URL is required.

## 6. Required runtime configuration

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEYS_JSON` | Preferred server-side JSON array used for live-search key rotation. |
| `GEMINI_API_KEY` | Optional single-key fallback for local compatibility. |
| `PUBLIC_LAUNCH_MODE=true` | Enables public quotas and protects developer routes. |
| `PUBLIC_UPLOADS_ENABLED=true` | Enables one temporary personal video per operation. |
| `VISITOR_COOKIE_SECRET` | Signs the opaque secure visitor cookie. Minimum 32 random bytes. |
| `IP_HASH_SECRET` | HMAC-hashes request IPs. Minimum 32 independent random bytes. |
| `UPSTASH_REDIS_REST_URL` | Durable atomic quota/idempotency store. |
| `UPSTASH_REDIS_REST_TOKEN` | Server-only Redis credential. |
| `ALLOWED_ORIGINS` | Exact public origin after the custom domain is connected. |

Optional provider and developer variables remain documented in `.env.example`.

## 7. Verification

```bash
curl https://YOUR_RUN_URL/api/health
curl https://YOUR_RUN_URL/api/public/samples
```

Then verify sample search, personal upload, quota persistence, result playback,
refresh behavior, another tab, mobile layout, `/tests`, `/design`, and
`/how-it-works`.

## Operational constraints

- Anonymous personal uploads are limited to 25 MB to remain below Cloud Run's
  HTTP/1 request limit after multipart overhead.
- Generated clips and uploads use the instance's temporary filesystem and can
  disappear on restart. They are intended for immediate demo playback.
- Keep at least one instance warm during the launch to avoid cold-start delay.
- Upstash must be available; paid live operations fail closed when the limiter
  is unavailable.
- Use project budgets, Gemini quotas, Cloud Run maximum instances, and Upstash
  limits together to bound launch costs.
