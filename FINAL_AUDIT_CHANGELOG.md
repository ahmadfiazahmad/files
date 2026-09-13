# VerifyAbroad-AI — Final Post-Audit Change Log

This build is a targeted correction of the existing project. It is not a rebuild.

## Confirmed integration fixes

- Preserved FastAPI UUID investigation IDs as strings throughout the frontend live-backend flow.
- Removed unconditional `Number(id)` coercion from live evidence upload paths.
- Fixed live investigation reopening so the server-rendered investigation page loads the FastAPI investigation.
- Added a FastAPI GET investigation endpoint returning transcript/evidence metadata and final-report status.
- Added a FastAPI investigation context-update endpoint.
- Added PostgreSQL `external_id` indexing to mirror live backend investigations for the History page.
- Updated live create/chat/evidence/verification/context flows to maintain the frontend investigation index.
- Fixed top-level `display_status` / `display_emoji` response mapping so risk UI does not render `undefined` confidence.
- Added a real live-backend verification action to the chat UI.
- Fixed live-backend mode state so the UI does not infer it from `NEXT_PUBLIC_API_BASE_URL`.
- Added the production `secure` flag to the auth cookie.
- Standardized the 10 MB evidence size error text and added the same 10 MB guard before live backend upload.
- Updated History to list only external backend investigations while live backend mode is enabled, avoiding accidental numeric-ID links to the wrong data store.
- Extended the backend structured-case JSON model with degree, funding, and scholarship context fields so profile edits survive reloads.

## Intentionally preserved

- Existing FastAPI verification pipeline.
- Existing SQLite + Railway Volume backend architecture.
- Existing Next.js UI and internal engine/demo mode.
- Existing Drizzle/PostgreSQL authentication and reference-data architecture.
- Existing Railway Nixpacks config files, because the deployed backend is already working and changing builders was not necessary for this corrective build.

## Verification performed in this environment

- Python backend source: `compileall` / `py_compile` clean.
- FastAPI/Pydantic new response models instantiated successfully.
- 79 frontend TypeScript/TSX source files passed TypeScript parser syntax diagnostics.
- A full frontend typecheck/build could not be rerun in this isolated environment because the uploaded project did not contain a complete installed dependency tree and outbound npm registry access was unavailable. The prior audit reported a successful `tsc --noEmit` and `npm run build` on the unmodified dependency environment before this final patch set; the code was additionally checked for syntax after the final changes.
- A full backend pytest run could not be rerun here because the isolated environment lacked runtime packages such as `google-genai`, `aiosqlite`, `groq`, and `tavily`, and package installation was blocked by unavailable network access.

These limitations are recorded rather than being represented as successful tests.


## Deployment-failure fixes

- Removed `frontend/railway.json` from the final frontend source because it forced the legacy Nixpacks config into the new Railway frontend service, overriding the dashboard's Railpack selection and causing the failed build to invoke Nixpacks. The frontend now relies on the Railway service settings (Root Directory `/frontend`, Railpack, detected `npm run build` / `npm run start`, `/api/health`).
- Fixed the live-create route's mirror record type: `getInvestigationByExternalId()` returns an `InvestigationRecord` with a string public id, while the PostgreSQL `appendMessage()` repository requires its internal numeric primary key. The route now reuses the numeric row returned by `ensureExternalInvestigation()`.
- Fixed a runtime import omission in the new FastAPI GET investigation endpoint by importing `EvidenceItem`.
- Added a regression assertion for `GET /investigations/{id}` to verify transcript, evidence, and top-level display status/emoji.
- Added a repository-root `.gitignore` covering frontend dependencies/build output, Python caches, environment files, and local runtime databases/uploads.

- Normalized mirrored external-investigation status values to the frontend's supported `gathering`/`assessed` states so backend intermediate statuses such as `verifying` do not leak into the frontend enum contract.
- Corrected the frontend context-client return type to the actual FastAPI `MessageResponse` shape and removed an unused external-investigation repository import.

## Re-audit pass (this session) — verified previous claims against actual source, found and fixed the remaining defect

Per instruction, every claim in the sections above was re-verified against
the actual attached source rather than trusted. Result: the great majority
of the previous audit's claimed fixes were confirmed genuinely present in
the code (UUID-safe routes, top-level `display_status`/`display_emoji`,
the new backend `GET /investigations/{id}` and `POST .../context`
endpoints, the `secure` auth cookie flag, the 10 MB evidence limit, History
correctly reading only externally-mirrored rows in live mode, and CORS
reading `CORS_ORIGINS` instead of a hardcoded wildcard). One real defect
remained unfixed and one deployment-config detail was stale:

1. **`useInvestigation.ts` — confirmed and fixed the exact TypeScript
   regression Railway's build failed on.** `ChatView.tsx` calls
   `useInvestigation({ investigation, mode: initialMode })`, but the
   hook's parameter type only declared `investigation`/`language` — no
   `mode` field — and the hook's own body read `initial?.mode` on line 61,
   which also didn't type-check against its own declared parameter type.
   This is a real, previously-unfixed defect (the earlier patch pass
   apparently addressed the call site's *usage* of `mode` but never
   updated the type it's checked against). **Fix:** added
   `mode?: "internal_engine" | "external_backend" | "mock_demo";` to the
   hook's `initial` parameter type in `src/hooks/useInvestigation.ts`,
   matching the existing optional-field pattern. This is the only change
   to that file.
2. **`ensureExternalInvestigation()` hardened against a real (if narrow)
   race.** `investigations.external_id` has a unique index
   (`db/schema.ts`), and the check-then-insert pattern in
   `ensureExternalInvestigation()`/`createInvestigation()` could throw an
   unhandled constraint-violation error if two requests for the same
   brand-new investigation raced (e.g. a chat message and an evidence
   upload firing back-to-back before the first insert commits). Fixed by
   catching the insert failure and re-reading the row the other request
   just created, instead of surfacing a 500.
3. **Backend evidence `mime` was always `null` for image evidence** in
   the new `GET /investigations/{id}` endpoint (`EvidenceItem` has no
   `mime` column at all — only `document` got a hardcoded
   `application/pdf`). Rather than add a migration for this cosmetic gap,
   inferred a reasonable mime type from the saved file's extension for
   images, since the upload endpoint already validated it was an
   `image/*` content type before saving.
4. **`DEPLOYMENT_GUIDE.md`'s `BACKEND_URL` guidance was stale** relative
   to the user's actual current Railway configuration. The guide
   recommended the backend's *public* HTTPS URL; the user's real Railway
   frontend service is already configured with
   `BACKEND_URL=http://${{files.RAILWAY_PRIVATE_DOMAIN}}:${{files.PORT}}`
   (Railway private networking). Private networking is strictly better
   here (internal traffic only, no public round-trip) and requires no
   code change — `backendClient.ts`'s `fetch()` works with either scheme.
   Updated the guide to recommend the private-networking value as
   primary, with the public URL kept as a documented fallback.

**Confirmed correct, not touched:** `investigate/route.ts`,
`investigation/[id]/message/route.ts`, `investigation/[id]/context/route.ts`,
`investigation/[id]/route.ts`, `investigation/[id]/verify/route.ts`,
`investigation/[id]/results/route.ts`, `evidence/route.ts`,
`backendAdapter.ts`, `backendClient.ts`, `session.ts`'s cookie config, and
`investigate/page.tsx` — every `Number(id)`/`parseInt` conversion in the
repo is confined to the internal-engine-only branches; the live-backend
paths carry the UUID as a string end-to-end. `NEXT_PUBLIC_API_BASE_URL`
appears only as a harmless same-origin-default fallback in
`services/api.ts` (never set in the deployment guide, never used to reach
FastAPI directly) and in comments — not a live issue.

**Testing performed this session:**
- `python3 -m py_compile` across all 48 backend `.py` files — clean.
- Node 22's native `--experimental-strip-types --check` (type-stripping
  syntax check, not full `tsc`) across every frontend `.ts` file (not
  `.tsx`, which that flag doesn't support) — clean, including the two
  edited files.
- **`npm install`, `tsc --noEmit`, `next build`, and `pytest` could NOT be
  run in this session** — outbound network access (npm registry) was
  blocked (`403 Forbidden`) and no `node_modules`/Python runtime
  dependencies were present in this sandbox. This matches the same
  limitation noted in the previous audit. The fixes above were verified by
  careful manual tracing of the exact TypeScript error Railway's build
  reported, not by re-running the build. **You should run
  `npm install && npm run typecheck && npm run build` yourself before
  redeploying** and report back if anything still fails — I'd rather say
  that plainly than claim an unrun build passed.

## Final targeted correction — `getInvestigation()` response mode type

- **File:** `frontend/src/services/api.ts`
- **Problem:** `useInvestigation.loadExisting()` consumes `response.mode`, but the `api.getInvestigation()` return type declared only `investigation`.
- **Correction:** Updated the return type to include `mode: "internal_engine" | "external_backend" | "mock_demo"`, matching the Next.js route response contract.
- **Backend changes:** None required for this TypeScript build issue.
- **Reason:** This is a frontend type-contract correction only; the backend API and database design remain unchanged.
