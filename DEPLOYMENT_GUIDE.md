# VerifyAbroad-AI — Railway Deployment Guide

Two services, deployed in this exact order:
1. Backend (FastAPI + SQLite on a Railway Volume)
2. Frontend Postgres database (Railway addon)
3. Frontend (Next.js)
4. Wire the two together, redeploy backend once with the real frontend URL

---

## Important architecture note (read first)

The frontend is dual-mode:
- When `BACKEND_URL` (server-side env var) is set, the Next.js server proxies
  investigation/evidence/verification calls to your FastAPI backend
  server-to-server. **The browser never calls FastAPI directly in this setup**,
  so CORS between browser and FastAPI is not actually exercised in normal use.
- Auth (`/api/auth/login`, `/api/auth/signup`, `/api/profile`) and
  `/api/health` use their **own separate Postgres database** via Drizzle,
  completely independent of `BACKEND_URL`. This is unconditional — the app
  will not build or boot without a real `DATABASE_URL` (Postgres).

**You therefore need two databases**: SQLite (backend, on a volume) and
Postgres (frontend, for accounts). This is not something we introduced —
it was already built into the frontend template. We kept your backend on
SQLite exactly as instructed.

CORS on the backend has still been locked down (not left wildcard) as
defense-in-depth, in case you ever set `NEXT_PUBLIC_API_BASE_URL` to make
the browser call FastAPI directly instead of proxying through Next.js.

---

## Step 1 — Deploy the backend

1. Create a new Railway project. Add a service from the `backend/` folder
   (GitHub repo or `railway up` from that directory).
2. **Attach a Volume**: in the service settings → Volumes → "New Volume".
   Mount path: `/data`.
3. Set these environment variables on the backend service:

   | Variable | Value |
   |---|---|
   | `ENVIRONMENT` | `development` (see note below) |
   | `DATABASE_URL` | `sqlite+aiosqlite:////data/app.db` |
   | `STORAGE_BACKEND` | `local` |
   | `LOCAL_UPLOAD_DIR` | `/data/uploads` |
   | `RAG_BACKEND` | `memory` |
   | `GEMINI_API_KEY` | your key |
   | `GROQ_API_KEY` | your key |
   | `TAVILY_API_KEY` | your key |
   | `OPENSANCTIONS_API_KEY` | your key (optional — degrades gracefully if blank) |
   | `CORS_ORIGINS` | `*` for now — you'll set this to the real frontend URL in Step 4 |
   | `APP_SECRET` | a random string |
   | `LOG_LEVEL` | `INFO` |

   **Why `ENVIRONMENT=development`**: the backend only auto-creates tables
   via `create_all()` in dev/test mode; in "production" mode it expects you
   to run `alembic upgrade head` yourself first. Since this is a single
   SQLite file on a volume with no separate migration step in your deploy
   pipeline, `development` is the simpler working option — table creation
   happens automatically against the volume-mounted file on first boot.
   (If you later add a release-phase step that runs `alembic upgrade head`
   before start, switch this to `production` — but that's optional here.)

4. Railway auto-detects Python via `runtime.txt` (pinned to 3.12) and uses
   the `Procfile`/`railway.json` start command:
   `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Deploy. Check `https://<backend-service>.up.railway.app/health` — should
   return `{"status": "ok", ...}` with `database: ok` and `hipo_reachable: ok`.
6. **Copy this backend URL** — you need it for the frontend in Step 3.

---

## Step 2 — Provision Postgres for the frontend

1. In the same Railway project, click "New" → "Database" → "Add PostgreSQL".
2. Railway automatically creates a `DATABASE_URL` variable on that Postgres
   service. Copy its value (or reference it via Railway's variable
   referencing, e.g. `${{Postgres.DATABASE_URL}}`, when setting the
   frontend's own `DATABASE_URL` in Step 3).
3. **Push the schema** (one-time, before or right after first frontend
   deploy) by running locally, with the Railway Postgres URL:
   ```bash
   cd frontend
   npm install
   DATABASE_URL="<railway-postgres-url>" npm run db:push
   ```
   This creates the `students`, `investigations`, `investigation_messages`,
   `evidence_items`, and reference-data tables via Drizzle. The app seeds
   reference data automatically on first read (`ensureSeeded()`), but the
   tables must exist first — `db:push` handles that.

---

## Step 3 — Deploy the frontend

1. Add a second Railway service from the `frontend/` folder.
2. Set these environment variables:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Railway Postgres URL from Step 2 |
   | `BACKEND_URL` | the backend's Railway URL from Step 1, e.g. `https://<backend-service>.up.railway.app` (no trailing slash) |
   | `GEMINI_API_KEY` | optional — only used by the internal fallback engine's LLM enrichment; harmless to set or leave blank since `BACKEND_URL` routes investigations to FastAPI instead |

   Leave `NEXT_PUBLIC_API_BASE_URL` **unset** — this keeps the browser
   talking to the Next.js app's own `/api/*` routes (same-origin), which
   then proxy server-side to `BACKEND_URL`. This is the simpler, more
   secure default and avoids needing real CORS configuration at all.

3. Railway auto-detects Node via `package.json`; `railway.json` sets the
   build/start commands (`npm run build` / `npm run start`), and `next start`
   automatically binds to Railway's injected `$PORT` (verified directly —
   no `-p` flag needed).
4. Deploy. Check `https://<frontend-service>.up.railway.app/api/health` —
   should return `{"ok": true}`.
5. **Copy this frontend URL.**

---

## Step 4 — Close the loop: set real CORS on the backend

Even though the browser won't call FastAPI directly in the default setup,
lock this down anyway as defense-in-depth:

1. Go back to the **backend** service's environment variables.
2. Set `CORS_ORIGINS` to the frontend's real Railway URL from Step 3, e.g.:
   ```
   CORS_ORIGINS=https://<frontend-service>.up.railway.app
   ```
   (Comma-separate multiple origins if you later add a custom domain.)
3. Redeploy the backend (Railway redeploys automatically on env var change,
   or trigger manually).

---

## Verifying the full chain works

1. Open the deployed frontend URL, sign up for an account (exercises
   Postgres).
2. Start a new investigation, send a message (exercises `BACKEND_URL` →
   FastAPI `/investigations`).
3. Upload a piece of evidence (exercises FastAPI's multipart upload →
   writes to `/data/uploads` on the volume).
4. Run verification (exercises Gemini/Groq/Tavily/OpenSanctions/Hipo).
5. Check the report renders with the emoji/status mapping.
6. Redeploy the backend once (e.g. trivial env var change) and confirm the
   investigation from step 2 is still there on `/investigations/{id}/results`
   — this proves the volume is actually persisting data across deploys,
   not just working within a single running instance.

---

## What was changed vs. left as-is

**Backend — changed:**
- `main.py`: CORS now reads `settings.cors_origins_list` (comma-separated
  env var) instead of a hardcoded `["*"]"`; methods restricted to
  GET/POST/OPTIONS; `allow_credentials=False`.
- `config.py`: added `cors_origins` setting + `cors_origins_list` property.
- Added `Procfile`, `railway.json`, `runtime.txt` (Python 3.12 pin).
- `.env.example`: added `CORS_ORIGINS`.

**Backend — left as-is:** all business logic, verification pipeline, RAG,
risk engine, database models, and the existing Alembic migration.

**Frontend — changed:**
- `.env.example`: corrected an inaccurate comment claiming `DATABASE_URL`
  was only needed in "internal engine mode" — it's actually required
  unconditionally for auth/health.
- `drizzle.config.json` → `drizzle.config.ts`: now reads `DATABASE_URL`
  from the environment instead of a hardcoded local connection string
  (verified this loads correctly).
- `package.json`: added `engines.node`, added a `db:push` script.
- Added `railway.json`.

**Frontend — left as-is:** all business logic, the internal deterministic
engine, the backend adapter/client, all UI/routes, the auth system.

**Verified directly (not just inspected):**
- Backend: clean `pip install` in a fresh venv, app imports, all 3 existing
  tests pass after the CORS change, and a real write to a volume-style
  absolute SQLite path (`/tmp/fake_volume/app.db`) succeeded.
- Frontend: `npm install`, `npm run build` (with a placeholder `DATABASE_URL`
  and `BACKEND_URL`), and `next start` correctly binding to a custom `$PORT`
  — all run for real, not assumed.

---

## Known risk: SQLite under concurrent load

You've deliberately chosen SQLite over Postgres for the backend. Flagging
the real trade-off: SQLite allows only one writer at a time. `aiosqlite`
serializes writes through a single connection, so under light-to-moderate
concurrent traffic (a handful of simultaneous verification runs) this is
fine — each write is fast and brief. Under heavier concurrent load (many
students running `/verify` at the same moment), writes will queue and
requests will slow down rather than fail outright, since SQLite handles
lock contention by waiting, not erroring, for reasonable timeout windows.
If you outgrow this, the migration path is what you already designed:
swap `DATABASE_URL` to Postgres — no other code changes needed, since the
codebase already uses SQLAlchemy async models portable across both.

---

# Post-audit integration notes (final corrected build)

The live deployment architecture remains intentionally split:

- **FastAPI backend:** SQLite on a Railway Volume mounted at `/data`.
- **Next.js frontend:** Railway PostgreSQL for accounts, reference data, and a small mirror/index of live backend investigations used for authenticated History listing.
- **Browser:** talks only to same-origin Next.js `/api/*` routes.
- **Next.js server:** talks to FastAPI through `BACKEND_URL` when live backend mode is enabled.

The frontend/backend integration was corrected so external FastAPI investigation IDs remain opaque UUID strings end-to-end. The frontend no longer converts them to JavaScript numbers.

The backend now also exposes a GET investigation endpoint with its stored chat transcript and evidence metadata, plus a context-update endpoint. This allows the frontend to reopen live investigations and edit the investigation profile without falling back to the internal demo engine.

The frontend PostgreSQL `investigations` table now includes nullable `external_id` values for live FastAPI investigations. After deploying the corrected frontend, run the normal Drizzle schema push once so this column/index exists:

```bash
npm run db:push
```

No backend SQLite migration is required for the new context fields because they are stored inside the existing JSON `structured_case` column.

The final live backend variables remain:

```text
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:////data/app.db
STORAGE_BACKEND=local
LOCAL_UPLOAD_DIR=/data/uploads
RAG_BACKEND=memory
CORS_ORIGINS=*
```

and the frontend live variables are:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
BACKEND_URL=https://<backend-domain>
```

Do not set `NEXT_PUBLIC_API_BASE_URL` for the Railway deployment.
