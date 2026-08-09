# Deployment

## The short version

**Frontend goes on Vercel. Backend cannot.** Deploy the backend to a container
host (Render / Railway / Fly.io) and point the frontend at it.

## Why the backend cannot run on Vercel

Not a preference. Four hard limits, any one of which breaks it:

| Limit | Vercel | What we need |
|---|---|---|
| Request body | 4.5 MB | Video uploads of 20-650 MB |
| Function duration | 10s hobby / 60s pro | 30s typical, minutes for long video |
| Filesystem | Ephemeral, per-invocation | Clips written by one request, served by a later one |
| Binaries | No ffmpeg | Every request cuts, transcodes, or samples video |

The body-size and filesystem limits are the fatal ones: a 4.5 MB cap makes
video upload impossible, and `/tmp` is not shared between invocations, so
`GET /api/quick/clip/...` would 404 even if the search succeeded.

---

## 1. Frontend on Vercel

Project root: `video_search_frontend`

| Setting | Value |
|---|---|
| Framework preset | Vite |
| Root directory | `video_search_frontend` |
| Build command | `npm run build` (default) |
| Output directory | `dist` (default) |

`vercel.json` is already committed and handles SPA rewrites, which the app
needs because routing uses the history API (`/developer`, `/tests` etc. would
otherwise 404 on refresh).

### Environment variable (Vercel dashboard → Settings → Environment Variables)

| Name | Value | Notes |
|---|---|---|
| `VITE_SEARCH_API_URL` | `https://your-backend.onrender.com` | No trailing slash. Must be HTTPS or the browser blocks it as mixed content. |
| `VITE_SITE_URL` | `https://your-public-site.example` | Canonical and social-sharing URL. Change this when the Vercel domain changes. |
| `VITE_ANALYTICS_ENDPOINT` | Optional | Privacy-reviewed first-party event collector. Leave unset to disable network analytics. |

That is the **only** variable the frontend needs. No API keys are baked into
the frontend build; anything a user types on `/developer` stays in their
browser's `sessionStorage`.

---

## 2. Backend on Render (fastest of the container hosts)

A `Dockerfile` is committed at the repository root.

1. New → Web Service → connect the repo
2. Runtime: **Docker**, root directory: repository root
3. Instance type: **at least 1 GB RAM** (ffmpeg re-encoding chunks in parallel)
4. Health check path: `/api/runtime/profiles`

### Backend environment variables

| Name | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | Gemini search, indexing, and voice. The one key that must be set. |
| `ALLOWED_ORIGINS` | **Yes** | Your Vercel URL, e.g. `https://footageask.vercel.app`. Comma-separated for several. |
| `OPENAI_API_KEY` | Only for GPT models | Needed if anyone selects an OpenAI model on `/developer`. |
| `GOOGLE_API_KEY` | Only for Drive | Drive folder listing. Falls back to `GEMINI_API_KEY` if unset. |
| `QUICK_DEMO_MODEL` | No | Default model. Defaults to `gemini-3.1-flash-lite`. |
| `ALLOWED_ORIGIN_REGEX` | No | Optional reviewed preview-origin regex. Production defaults to no regex; prefer exact `ALLOWED_ORIGINS`. |
| `PUBLIC_LAUNCH_MODE` | Launch only | Set `true` to enforce sample-only public search, durable limits, and developer protection. |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | Launch only | Durable atomic usage and idempotency store. |
| `VISITOR_COOKIE_SECRET` / `IP_HASH_SECRET` | Launch only | Independent server-only random secrets, at least 32 bytes each. |
| `PUBLIC_SAMPLE_*_PATH` | Launch only | Backend paths for approved sample media. Paths are never returned to browsers. |
| `DEVELOPER_FEATURES_ENABLED` / `DEVELOPER_ADMIN_TOKEN` | Production developer access | Keep disabled unless protected admin access is required. |

Users can also paste their own keys on `/developer` at runtime, which override
the server's for that request and are never persisted.

---

## 3. Where to get each key

| Key | Where | Cost |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Free tier available |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Paid, per-token |
| Drive access | Same Google Cloud project as the Gemini key. **Enable the Drive API**: console → APIs & Services → Enable APIs → "Google Drive API" | Free |

Drive folders must be shared as **"anyone with the link"**. There is no OAuth
flow, deliberately.

---

## 4. Order of operations

1. Deploy the backend first, note its URL
2. Set `ALLOWED_ORIGINS` on the backend once you know the Vercel URL
3. Deploy the frontend with `VITE_SEARCH_API_URL` pointing at the backend
4. Redeploy the frontend after changing that variable — Vite inlines it at
   **build** time, so a change does not take effect until you rebuild

## 5. Checking it works

```bash
curl https://your-backend.example.com/api/runtime/profiles
```

Then open the Vercel URL and run a search. If the browser console shows a CORS
error, `ALLOWED_ORIGINS` does not match your actual Vercel origin.

## Known constraints in production

- **Cold starts.** Render's free tier sleeps after inactivity; the first
  request can take ~50s to wake. Use a paid instance for a live demo.
- **Upload time.** A 600 MB video over a conference connection is the slowest
  part of the run, not the model.
- **Clip lifetime.** Cut clips live in the container's temp directory and are
  lost on restart or redeploy. Fine for a demo; a persistent store would be
  needed for anything real.
