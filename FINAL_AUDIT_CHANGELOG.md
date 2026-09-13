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
