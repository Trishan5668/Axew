# AXEW Cloud Integration

AXEW remains **local-first by default**. The cloud features in this folder —
Supabase auth, Razorpay billing, and OpusClip post-processing — are opt-in
behind a single feature flag. With the flag off, the editor behaves exactly
as it did before this integration landed.

This document covers:

1. The hybrid feature flag and what it gates
2. Required environment variables
3. Applying the Supabase migrations
4. Running the cloud test suite locally
5. Building the Windows installer (Track 4)
6. The list of things that are intentionally **verification-pending**

---

## 1. The hybrid feature flag

Two env vars control the flag:

| Variable | Process | Purpose |
| --- | --- | --- |
| `AXEW_CLOUD_ENABLED` | AI service (Python) | Mount `/opusclip/process`, `/payments/*`, `/cloud/status` |
| `VITE_AXEW_CLOUD_ENABLED` | Desktop renderer | Render `/login`, `/dashboard/billing`, `OpusClipPanel`, `UserMenu`, `RequireAuth` |

If `VITE_AXEW_CLOUD_ENABLED=false`, the renderer skips React Router entirely
and mounts the original `MainLayout` directly — there is zero behavioral
change for local-only users.

`apps/desktop/src/lib/cloudFlag.ts` is the single source of truth on the
frontend. `apps/ai-service/middleware/cloud_config.py` is the single source
of truth on the backend. Do not read the underlying env vars anywhere else.

---

## 2. Environment variables

See `.env.example` for the full set. Minimum cloud-mode setup:

```
# AI service (apps/ai-service)
AXEW_CLOUD_ENABLED=true
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...           # service-role, NEVER ship to renderer
SUPABASE_JWT_SECRET=YOUR_PROJECT_JWT_SECRET
RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxx
OPUSCLIP_API_KEY=sk-...                    # do NOT paste into chat or commits
OPUSCLIP_BASE_URL=https://api.opus.pro

# Desktop renderer (apps/desktop) — Vite reads VITE_* at build time
VITE_AXEW_CLOUD_ENABLED=true
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...              # anon key only, never service-role
VITE_RAZORPAY_KEY_ID=rzp_test_xxxxxxxx     # same KEY_ID, no secret
VITE_AXEW_AI_BASE_URL=http://127.0.0.1:7002
```

**The OpusClip API key lives only on the AI service.** The renderer never
sees it; the renderer talks to the AI service, the AI service forwards to
OpusClip with the secret attached server-side.

---

## 3. Supabase migrations

Migrations live in `supabase/migrations/`. Apply with the Supabase CLI:

```bash
supabase db reset            # local dev: rebuild from migrations/
supabase db push             # remote: apply against linked project
```

| File | Purpose |
| --- | --- |
| `0001_init.sql` | Enable `pgcrypto` / `uuid-ossp` extensions |
| `0002_auth_profiles.sql` | `public.profiles` table + RLS + auto-create trigger granting 10 free credits |
| `0003_payments.sql` | `public.payments` ledger + RLS + idempotent `apply_payment_credits` / `mark_payment_failed` / `refund_payment_credits` RPCs |
| `0004_credit_rpc.sql` | Atomic `deduct_credits` RPC + `get_credit_summary` |

RLS policies are enabled on every new table. The free-tier credit grant
happens only inside the SQL trigger — no client-side code path can set
`credit_balance` directly.

### SQL trigger / RPC verification

A pgTAP-style smoke test lives at `supabase/tests/test_handle_new_user.sql`.
It exercises the three critical invariants — free-tier grant, atomic credit
deduction, and idempotent payment-credit application — using only plain
`RAISE EXCEPTION` so no extensions are required:

```bash
supabase db reset
psql "$(supabase status -o env | grep DATABASE_URL | cut -d= -f2 | tr -d '"')" \
     -f supabase/tests/test_handle_new_user.sql
```

The script wraps everything in `BEGIN…ROLLBACK` so it never persists test
rows. Look for `NOTICE: PASS:` lines in the output.

After applying migrations, regenerate `apps/desktop/src/lib/database.types.ts`:

```bash
supabase gen types typescript --linked > apps/desktop/src/lib/database.types.ts
```

A hand-written version is shipped as a baseline.

---

## 4. Running the tests

### AI service (pytest)

```bash
cd apps/ai-service
pip install -r requirements.txt
pytest tests/
```

The tests use:

- An in-memory fake of `supabase-py` (see `tests/conftest.py`).
- `respx` to mock the OpusClip HTTP API.
- The real `python-jose` JWT signing path against a fixed test secret.

Coverage (21 backend tests, all passing):

| Test | What it asserts |
| --- | --- |
| `test_opusclip::test_happy_path_*` | Feature flags posted, credits deducted, response shape |
| `test_opusclip::test_polling_*` | Exponential backoff, eventual success, max-retries timeout |
| `test_opusclip::test_insufficient_credits_*` | 402 returned, OpusClip never called |
| `test_opusclip::test_missing_jwt_*` | 401 returned |
| `test_opusclip::test_cross_account_*` | 403 returned |
| `test_payments::test_create_order_*` | Razorpay order created, payment row inserted |
| `test_payments::test_webhook_signature_rejection*` | Invalid HMAC → 400, no credits |
| `test_payments::test_idempotent_webhook*` | Replay → credits applied exactly once |
| `test_payments::test_webhook_amount_mismatch_rejected` | Webhook amount ≠ order amount → 400, payment marked failed |
| `test_payments::test_webhook_currency_mismatch_rejected` | Non-INR currency → 400, no credits |
| `test_payments::test_webhook_payment_failed_*` | `payment.failed` event marks row; never downgrades a paid order |
| `test_payments::test_webhook_refund_*` | `refund.processed` event subtracts credits; unknown payment is no-op |
| `test_payments::test_payment_status_*` | Reconciliation endpoint returns current state; cross-user lookup → 404 |
| `test_payments::test_plans_endpoint_is_public` | `/payments/plans` works pre-auth |

### Desktop (vitest)

```bash
cd apps/desktop
pnpm install
pnpm test
```

Coverage (10 frontend tests, all passing):

| File | What it asserts |
| --- | --- |
| `src/tests/auth.test.tsx` | LoginPage two-step flow, OTP resend cooldown, RequireAuth redirect, `from` preservation, refresh-on-expiry → `?error=session_expired`, OAuthCallbackPage exchange + error surfacing |
| `src/tests/billing.test.tsx` | BillingPage renders all 3 plans + free-tier copy + balance |

---

## 5. Building the Windows installer (Track 4)

```bash
pnpm install
pnpm build                         # turbo build all packages
pnpm make-installer                # runs apps/desktop/scripts/build-installer.mjs
```

By default this packages only the JS/TS app (the renderer + Electron main).
To produce the full self-contained installer:

```bash
$env:AXEW_BUILD_RUST = "1"
$env:AXEW_BUILD_RUNTIME = "1"
$env:AXEW_PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
$env:AXEW_FFMPEG_ZIP_URL  = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
pnpm make-installer
```

The output appears in `apps/desktop/release/`:

```
release/
 ├── AxewSetup-<version>.exe      # NSIS installer (~150–300 MB)
 ├── Axew-<version>.exe           # portable build
 └── latest.yml                   # auto-update manifest
```

### Whisper model strategy

**Models are NOT bundled in the installer.** On first launch the
`FirstRunWizard` lets the user pick between Turbo (~1.5 GB) and Large-v3
(~3 GB). Downloads are resumable and cached in `%APPDATA%/Axew/models/`.
See `apps/desktop/electron/services/modelManager.ts`.

### Auto-update

`electron-updater` is wired in `apps/desktop/electron/services/autoUpdater.ts`.
The `publish:` section of `electron-builder.yml` is intentionally `null` so
that a misconfigured release channel surfaces immediately instead of
silently shipping unsigned updates. To enable updates, set `publish:` to a
GitHub Releases or S3 channel and rebuild.

---

## 6. OAuth in Electron — what's wired

PKCE OAuth in a packaged Electron app needs more than a plain
`window.location.origin` callback (the renderer loads from `file://`,
which Supabase will refuse to redirect to). We solve this with a custom
`axew://` URL protocol:

- `apps/desktop/electron/services/oauthHandler.ts` registers `axew://`
  with the OS, acquires a single-instance lock so a second-launch carries
  the deep link back to the existing process, and forwards the URL to the
  renderer over IPC channel `oauth:deep-link`.
- `apps/desktop/electron/main.ts` calls `registerOAuthProtocol()` +
  `attachOAuthDeepLinkListeners({…})` before `app.whenReady()`.
- The renderer reads the redirect URL via `axew.auth.getOAuthRedirectUrl()`
  IPC, which returns `axew://auth/callback` in packaged builds and
  `http://localhost:5173/auth/callback` in dev. **Add both URLs to
  Supabase Auth → URL Configuration → Redirect URLs**, otherwise OAuth
  rejects the redirect.
- `apps/desktop/src/App.tsx` mounts an `OAuthDeepLinkRouter` that listens
  for `oauth:deep-link` IPC events and navigates to `/auth/callback` so
  the page can finish the PKCE exchange — covers the case where the user
  is still on `/login` when the deep link arrives.

---

## 7. Verification-pending checklist

Most of the original verification-pending items are now in-code (with
tests). The remainder require live service accounts that the development
environment doesn't have.

| Area | What still needs a live test |
| --- | --- |
| Supabase migrations | Run `supabase db reset` against an actual project, then `psql -f supabase/tests/test_handle_new_user.sql` — the script's assertions are written but were only exercised against the in-memory fake |
| Supabase OAuth | Real Google PKCE flow through `axew://auth/callback` (deep-link plumbing + redirect URL listing in Supabase dashboard) |
| Supabase asymmetric JWT | Confirm an ES256/RS256-signed token decodes against the project's live JWKS endpoint |
| Razorpay create-order | Hit the real Razorpay test API and confirm the order id round-trips into our `payments` table |
| Razorpay webhook | Tunnel via ngrok / cloudflared, trigger test payment + failure + refund, confirm credits flow exactly once in each direction |
| OpusClip API | Confirm `/v1/clips` payload shape + polling endpoint + `viral_score` semantics against the real OpusClip account |
| Whisper model download | Resume across a network drop and verify SHA-256 once we pin checksums |
| Installer on clean Windows VM | `AxewSetup-<version>.exe` must install + launch on a VM with NO Node/Python/Rust/FFmpeg |
| Auto-update channel | Wire `publish:` to a real release backend (GitHub Releases / S3) and confirm `latest.yml` is consumed correctly |
| Embedded Python runtime | `bundle-runtime.mjs` currently downloads archives; extraction + `pip install -r requirements.txt -t site-packages` step needs to be automated |

### Recently moved out of verification-pending

The following items were marked verification-pending in the previous
iteration but are now covered by tests against the in-memory fakes:

- Webhook idempotency (replay → exactly one credit application)
- Webhook signature rejection (invalid HMAC → 400, no credit)
- Webhook amount + currency mismatch rejection
- Webhook `payment.failed` + `refund.processed` event handling
- Reconciliation endpoint (`GET /payments/{id}/status`) including cross-user 404
- RequireAuth refresh-on-expiry path (refresh failure → `/login?error=session_expired`)
- LoginPage OTP resend cooldown + error query-param surfacing
- OAuthCallbackPage exchange success + failure paths
- JWT verification of asymmetric (ES256/RS256) tokens via cached JWKS
