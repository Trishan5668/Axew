# OpusClip Integration — Setup Guide

This document explains how to wire OpusClip into a running AXEW
deployment, where to put credentials, what to test, and what live
verification steps still require a real OpusClip account.

> **Scope.** AXEW uses OpusClip as a **post-processor only**. Long-form
> retrieval and clip-range selection remain owned by AXEW's own
> Whisper + hybrid retrieval pipeline. OpusClip is invoked per
> AXEW-selected range to layer on viral curation, dynamic captions,
> filler-word removal, B-roll and speaker reframing.

---

## 1. Where to place the API key

OpusClip credentials live **only** in the AI service environment. The
desktop / renderer process never sees the key — every OpusClip call is
proxied through `apps/ai-service/routers/opusclip.py`.

### Local development

1. Copy the example env file:

   ```bash
   cp apps/ai-service/.env.example apps/ai-service/.env
   ```

2. Edit `apps/ai-service/.env` and add:

   ```bash
   AXEW_CLOUD_ENABLED=true
   OPUSCLIP_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

3. (Optional) Override the API base URL if you're testing against a
   staging instance:

   ```bash
   OPUSCLIP_BASE_URL=https://api.opus.pro
   ```

The AI service loads `apps/ai-service/.env` automatically on startup via
`python-dotenv` (see the top of `main.py`). It honors the variable
without any prefix — do **not** add `AXEW_` in front of `OPUSCLIP_API_KEY`.

### Production / packaged Electron

For the packaged desktop build, the AI service runs as a child process
of the Electron main process. Bundle a per-user override file at:

```
%APPDATA%/Axew/ai-service.env        (Windows)
~/Library/Application Support/Axew/ai-service.env   (macOS)
~/.config/Axew/ai-service.env        (Linux)
```

Then have the Electron main process pass `--env-file=<path>` (or
`AXEW_AI_SERVICE_ENV=<path>`, depending on your launcher) before starting
the Python service. **Never** ship a build with a non-empty
`OPUSCLIP_API_KEY` baked into source or asar archives.

### Required environment variables (reference)

| Variable | Required? | Default | Notes |
|---|---|---|---|
| `AXEW_CLOUD_ENABLED` | yes | `false` | Must be `true` to expose any `/opusclip/*` route. |
| `OPUSCLIP_API_KEY` | yes | _(empty)_ | Bearer token from the OpusClip dashboard. |
| `OPUSCLIP_BASE_URL` | no | `https://api.opus.pro` | Override only for staging. |
| `SUPABASE_URL` | yes | _(empty)_ | Needed to verify user JWTs that submit jobs. |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | _(empty)_ | Needed for the credit-deduction RPC. |
| `SUPABASE_JWT_SECRET` | yes (HS256) | _(empty)_ | Or rely on JWKS auto-discovery for asymmetric tokens. |

If any of the required values are missing, `POST /opusclip/process`
returns `503 Service Unavailable` with a message naming the missing
variable — **before** any external API call.

---

## 2. API surface (AXEW backend)

All three endpoints require a valid Supabase JWT in the
`Authorization: Bearer …` header and are rooted at the AI service base
URL (default `http://127.0.0.1:7002`).

### `POST /opusclip/process`

Register an AXEW job and start background processing. Returns
**202 Accepted**.

```json
{
  "video_url": "https://media.example.com/talk.mp4",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "clips": [
    { "start_seconds": 30,  "end_seconds": 120, "label": "intro" },
    { "start_seconds": 360, "end_seconds": 480, "label": "punchline" }
  ],
  "curation_model": "ClipBasic",
  "aspect_ratio": "portrait",
  "remove_fillers": true,
  "enable_broll": true,
  "enable_captions": true,
  "source_language": "auto",
  "topic_keywords": ["axew", "opusclip"]
}
```

Response:

```json
{
  "job_id": "fbe6c0a4d3...",
  "stage": "queued",
  "minutes_required": 3.5,
  "credits_balance_before": 87.0,
  "poll_status_url": "http://127.0.0.1:7002/opusclip/status/fbe6c0a4d3...",
  "poll_result_url": "http://127.0.0.1:7002/opusclip/result/fbe6c0a4d3..."
}
```

Error codes:

| Code | Meaning |
|---|---|
| `402` | Insufficient credits — no OpusClip call made. |
| `403` | Caller's JWT does not match `user_id` in the body. |
| `429` | This user already has `MAX_ACTIVE_JOBS_PER_USER` (5) jobs running. |
| `503` | OpusClip / Supabase environment incomplete. |

### `GET /opusclip/status/{job_id}`

Returns the aggregated stage of the AXEW job plus per-OpusClip-project
stages. Poll every 3–5 seconds.

```json
{
  "job_id": "fbe6c0a4d3...",
  "stage": "processing",
  "minutes_required": 3.5,
  "submitted_at": 1718990000.123,
  "updated_at":   1718990010.456,
  "projects": [
    { "project_id": "P_abc", "source_range": {"start_seconds": 30,  "end_seconds": 120, "label": "intro"},     "stage": "RENDER",   "last_error": null },
    { "project_id": "P_xyz", "source_range": {"start_seconds": 360, "end_seconds": 480, "label": "punchline"}, "stage": "COMPLETE", "last_error": null }
  ],
  "error_message": null
}
```

AXEW stage values: `queued`, `submitting`, `processing`, `completed`,
`failed`, `expired`. Per-project stages mirror OpusClip's raw enum
(`PENDING | QUEUED | CURATE | REFINE | RENDER | UPLOAD | COMPLETE | STALLED`).

`404` is returned (not `403`) when a different user owns the job, to
avoid leaking existence.

### `GET /opusclip/result/{job_id}`

Only valid once `stage == "completed"`. Returns the normalized clips:

```json
{
  "job_id": "fbe6c0a4d3...",
  "stage": "completed",
  "minutes_processed": 3.5,
  "credits_remaining": 83.5,
  "results": [
    {
      "opusclip_id": "P_abc.CU_001",
      "project_id":  "P_abc",
      "clip_url":    "https://cdn.opus.pro/.../export.mp4",
      "preview_url": "https://cdn.opus.pro/.../preview.mp4",
      "duration_seconds": 42.5,
      "title": "Why everyone gets distributed systems wrong",
      "description": "...",
      "hashtags": "#tech #systems",
      "keywords": ["systems", "design"],
      "transcript_text": "...",
      "viral_score": 84,
      "source_range": { "start_seconds": 30, "end_seconds": 120, "label": "intro" }
    }
  ]
}
```

* `425 Too Early` — job is not yet complete; keep polling `/status`.
* `409 Conflict` — job failed; `detail` carries the user-facing reason.
* `404 Not Found` — unknown id or owned by a different user.

Credits are deducted **exactly once**, atomically, when the worker
flips to `completed`. Failed / expired jobs do NOT charge credits.

---

## 3. How the request is mapped onto OpusClip

For each `ClipRange` in the request we POST one project to
`https://api.opus.pro/api/clip-projects` with:

```jsonc
{
  "videoUrl": "<request.video_url>",
  "curationPref": {
    "model": "ClipBasic",
    "clipDurations": [[0, 90]],
    "range": { "startSec": 30.0, "endSec": 120.0 },
    "genre": "Auto",
    "skipCurate": false,
    "topicKeywords": ["axew", "opusclip"]   // only when model=ClipBasic
  },
  "renderPref": {
    "layoutAspectRatio": "portrait",
    "enableCaption": true,
    "enableBroll": true,
    "quickstartConfig": { "enableRemoveFillerWords": true }
  },
  "importPref":  { "sourceLang": "auto" },
  "uploadedVideoAttr": { "title": "intro" }
}
```

We then poll `GET /api/clip-projects/{projectId}` until `stage` is
`COMPLETE` (or `STALLED`), and fetch results via
`GET /api/exportable-clips?q=findByProjectId&projectId={projectId}`.

### Defensive parsing

The OpusClip response schema is camelCase, nested, and (per the public
docs) does NOT always expose virality. The parser in
`apps/ai-service/services/opusclip_client.py` tolerates:

* Top-level vs. `{data: [...]}`-wrapped array shapes
* `uriForExport` (preferred) → falls back to `uriForPreview` → `output.url`
* `durationMs` (preferred) → `durationSeconds` / `duration`
* `viralityScore` / `viralScore` / `score` / `scores.viral` — surfaced
  as a 0..100 number, or `null` when absent
* Malformed individual clips are **skipped** rather than failing the
  whole batch (with a `WARNING` log entry).

---

## 4. How to test against a sample video (no real key required)

The pytest suite mocks every external HTTP call via `respx`. To
exercise the full happy path locally:

```bash
cd apps/ai-service
python -m pytest tests/test_opusclip.py -v
```

You should see 19 tests pass, covering:

* `parse_*` defensive shape tests (5 cases — including missing virality,
  wrapped array, malformed clip, preview-only)
* `build_create_project_payload_*` request-shape tests (2 cases for
  ClipBasic vs. ClipAnything)
* The full `POST /process → poll /status → GET /result` happy path,
  including credit deduction and the absence of `uriForExport` leaks
* `402` insufficient-credits gate (asserts no OpusClip call was made)
* `403` cross-user submission rejection
* `404` cross-user status lookup
* `409` result-after-failure
* `425` result-before-completion
* `429` per-user job-limit enforcement
* Rate-limit / `429`-backoff retry success path
* `payment.failed` → credits untouched

---

## 5. How to test with a real OpusClip account

Once you have a Pro (Beta), Max or Business plan API key from the
[OpusClip dashboard](https://www.opus.pro/api):

1. Populate `apps/ai-service/.env`:

   ```bash
   AXEW_CLOUD_ENABLED=true
   OPUSCLIP_API_KEY=sk_live_...
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   SUPABASE_JWT_SECRET=...
   ```

2. Start the AI service:

   ```bash
   cd apps/ai-service
   python -m uvicorn main:app --reload --port 7002
   ```

3. Verify cloud status:

   ```bash
   curl http://127.0.0.1:7002/cloud/status
   # → { "opusclip_configured": true, ... }
   ```

4. From the Electron app, sign in, drop a sample MP4 (or paste a
   YouTube link) into the MediaBin, right-click a timeline range and
   choose "Send to OpusClip", then click **Enhance with OpusClip**.

5. Recommended sample sources:
   * Any public YouTube talk (`https://www.youtube.com/watch?v=…`)
   * A 60-second public MP4 hosted on S3 / GCS
   * **Note**: OpusClip needs at least ~30 seconds of footage in the
     selected range to produce useful viral candidates.

6. Expected timeline:
   * `submitting` → `processing` within ~1 s
   * `processing` → `completed` typically in 1–5 minutes
   * On `completed`, the panel populates with one or more "Enhanced
     clips" cards. Click **Preview** to open the CDN preview MP4 and
     **Import to Timeline** to add the high-res export as a new
     MediaFile + clip on track 1.

---

## 6. Logging and diagnostics

The integration emits structured logs under the `services.opusclip_client`
and `routers.opusclip` loggers:

```
INFO  routers.opusclip      OpusClip job created: <id> user=<uid> ranges=2 minutes=2.0
INFO  services.opusclip_client OpusClip create-project label='intro' range=30.00-120.00s
INFO  services.opusclip_client OpusClip project created: P_abc
WARN  services.opusclip_client OpusClip rate-limited (attempt 1). retry_after=2.0
WARN  services.opusclip_client OpusClip transient error 503 (attempt 2)
INFO  routers.opusclip      Job <id> completed: deducted 2.00 minutes, balance now 8.00
```

Enable DEBUG to see every request/response payload (note: keep DEBUG off
in production — request payloads include the source video URL):

```bash
AXEW_LOG_LEVEL=debug python -m uvicorn main:app --port 7002
```

If a job stalls, inspect:

* `GET /opusclip/status/{id}` — look at each per-project `stage` and
  `last_error`.
* The OpusClip dashboard — search for the `projectId` reported by
  `/status` and review the project's stage there directly.
* AI service logs — every retry / 429 / 5xx is logged with attempt
  number.

---

## 7. Remaining live-verification steps

The following items require a real OpusClip account to verify in full
and are **not** covered by the in-memory test suite:

1. **Bearer auth against `api.opus.pro`** — the test suite asserts the
   `Authorization` header is set, but only a real key proves OpusClip
   accepts it. Action: run a one-clip job from the Billing-enabled
   account and confirm `stage: completed` in `/status`.
2. **Project lifecycle wall-clock timing** — verify a typical 1-minute
   range completes within the 30-minute worker ceiling defined in
   `routers/opusclip.py::_WORKER_MAX_RUNTIME_S`.
3. **Real `viralityScore` field name** — the docs do not pin it down.
   On a live job, capture the raw `/api/exportable-clips` response and
   confirm the value is surfaced by the defensive parser; if OpusClip
   uses a name we did not anticipate, add it to the alias list in
   `services.opusclip_client._parse_one_clip`.
4. **Rate-limit headers** — the test suite mocks `Retry-After: 0`. Run
   a burst of >30 submissions in one minute and confirm the client's
   exponential backoff respects the real `Retry-After` value.
5. **Storage URL TTL** — `uriForExport` / `uriForPreview` are CDN URLs
   with unspecified expiry. If you observe 403s on later previews,
   re-fetch `/api/exportable-clips` to refresh them.
6. **Webhook signature verification** — we currently poll, but OpusClip
   supports `conclusionActions: [{type: "WEBHOOK", url: ...}]` with
   `X-Opus-Signature` / `X-Opus-Salt` / `X-Opus-Timestamp` headers. A
   future iteration can replace the polling worker with a webhook
   endpoint; until then the polling path is the only verified mode.
