# Backend review: findings and changes

Full code audit performed by reading every file in the codebase (~1,800
lines across 41 Python files). **I did not have outbound network access in
the environment this review was performed in**, so I could not `pip
install` into a clean venv, run the test suite myself, or make live API
calls. Everything below was verified by careful static reading and, where
noted, targeted web research (current Gemini/Groq model IDs, known
supabase-py dependency conflicts). Please run `pip install -r
requirements.txt` and the test suite yourself and report back if anything
doesn't check out — I'd rather say that plainly than claim untested code is
confirmed working.

## Confirmed working as designed (no change needed)

- **Tavily + Gemini Google Search run in parallel as two independent
  sources**, each producing its own `EvidenceRecord` — not a fallback
  chain. Confirmed in `verification/institution.py`, `verification/agent.py`,
  `verification/payment.py`. This matches your description exactly.
- **Multi-turn counter-questioning investigation flow** — preserved exactly.
  `agents/investigator.py` / `api/investigation.py` still ask one missing
  field at a time and only flip `ready_for_verification` once
  `StructuredCase.is_sufficient_for_verification()` is satisfied.
- **`data/hec_recognized.json` and `data/banned_agents.json` are genuinely
  empty placeholders** with explanatory `note` fields, exactly as you said.
  `data/loader.py`'s fuzzy-match loop handles an empty list safely (returns
  `None`, no crash) — verified by reading the loop logic.
- **Risk score is locked to the deterministic engine's output.** The LLM
  narrative step cannot influence `risk_score`/`risk_level` — this is now
  structurally true, not just an after-the-fact overwrite (see below).
- **Gemini model `gemini-3.8-flash` and Groq model `qwen/qwen3.8-27b`** —
  both verified as real, current model IDs via web search against Google's
  and Groq's own docs (as of Sept 2026). No change made.
- **`gemini-embedding-001`** — verified current and GA.
- **requirements.txt version pins** — researched supabase-py 2.31.0's own
  dependency pins (pydantic 2.11.x, httpx 0.28.1); both fall inside this
  project's existing constraints (`pydantic>=2.11.7,<3.0`,
  `httpx>=0.28.1,<1.0`). No known conflict found. Not verified by an actual
  install (no network) — please confirm with a clean-venv install.

## Real bugs found and fixed

1. **Dead risk rule (`risk/risk_engine.py`).** The "urgent payment" rule
   checked for the substring `"urgency"` in evidence text, but the only
   place that generates this text (`verification/document.py`,
   `check_payment_deadline_urgency`) writes `"...urgent payment deadline..."`
   — never `"urgency"`. The rule silently never fired. Fixed the substring
   match to `"urgent"` (covers both).

2. **Two risk rules declared but never used.** `RULES["contradicted_program"]`
   and `RULES["payment_process_mismatch"]` existed in the `RULES` dict but
   `compute_risk_score()` never referenced them — dead weight, and a real
   scoring gap (a document that claims a different program, or a payment
   amount that doesn't match what the student stated, went unscored). Wired
   both in:
   - `contradicted_program` fires when any contradicted evidence record's
     claim mentions "program" (i.e. the document-vs-case consistency check
     in `verification/document.py` caught a mismatch).
   - `payment_process_mismatch` fires when a `consistency_rule`-sourced
     contradicted record concerns the payment domain (amount/method
     mismatch between what was uploaded and what was stated in chat).

3. **Final report LLM was asked to reproduce the entire evidence tree.**
   The original `agents/final_analyst.py` had the LLM generate the *whole*
   `FinalReport`, including `domains: list[DomainSummary]` with each
   domain's full `evidence: list[EvidenceRecord]` re-transcribed by the
   model. This directly undermines your stated principle — "no single AI
   opinion makes the final call; every conclusion is traceable to evidence,
   and the AI only organizes/presents that evidence" — because it has the
   LLM copy structured data it didn't generate, risking dropped/altered
   fields, and is fragile under the Groq JSON-mode fallback (materially
   worse at deep nested-schema compliance than Gemini's schema-constrained
   decoding — a Gemini outage could turn "narrative slightly worse" into
   "verification pipeline throws a 502").

   **Fix:** the LLM now only produces `fraud_signals` / `recommendation` /
   `safer_action` (new `LLMNarrative` schema). Every domain's
   status/summary/evidence list is assembled deterministically in Python
   (`_assemble_domains()` in `agents/final_analyst.py`), directly from the
   aggregator's output and the already-validated `EvidenceRecord` objects.
   The LLM cannot invent or drop evidence because it's never asked to
   re-emit it. If narrative generation fails entirely (both providers
   down), the run still completes with a template-based narrative instead
   of a 502 — the deterministic score/evidence never depended on the LLM
   call succeeding.

4. **`report.manual_checks` was assigned raw dicts**, not `ManualCheck`
   model instances, bypassing Pydantic validation on assignment. Fixed to
   construct real `ManualCheck(...)` objects.

5. **No per-call timeouts anywhere.** `asyncio.gather()` runs sources
   concurrently, but a single hung Gemini/Groq/Tavily call would have
   blocked the whole `gather()` (and therefore the whole `/verify` request)
   indefinitely. Added `asyncio.wait_for(..., timeout=...)` around every
   Gemini call, Groq call, and Tavily call, with the timeouts configurable
   via `LLM_CALL_TIMEOUT_SECONDS` / `WEB_RESEARCH_CALL_TIMEOUT_SECONDS` in
   `.env` (Hipo and OpenSanctions already had `httpx` timeouts set — left
   as-is).

6. **Every exception/fallback path was silent — no logging.** Gemini→Groq
   fallback, Tavily/Hipo/OpenSanctions failures, and Gemini Google Search
   grounding failures all caught broad `Exception` and returned an
   `{"error": ...}` dict with zero logging. A real outage would have been
   invisible until someone noticed suspiciously empty reports. Added
   `logging_config.py` (central setup, called once in `main.py`) and
   `logger.warning`/`logger.error` calls at every one of these points.

7. **One malformed LLM response could kill the entire verification run.**
   `agents/normalizer.py` had no error handling — if the LLM's JSON didn't
   validate against `NormalizedResult`/`VerificationResult` (or the call
   failed entirely after the Groq fallback also failed), the exception
   propagated up through `asyncio.gather()` in `verification/institution.py`
   / `agent.py` / `payment.py`, all the way to the top-level `try/except`
   in `api/verification.py`, which would mark the *whole* investigation
   `verification_failed` and return a 502 — even though only one of a dozen
   sources actually failed. Fixed: `normalize_source_result()` now catches
   that failure, logs it, and degrades just that one source to
   `unable_to_verify` (which the aggregator already treats conservatively)
   instead of aborting the run.

## Gaps filled (per your explicit list)

- **Logging on every fallback/exception path** — see #6/#7 above.
- **Input validation on API endpoints:**
  - `POST /investigations` / `POST /investigations/{id}/messages` reject
    empty/whitespace-only messages (400).
  - `POST /investigations/{id}/messages` rejects continuing a chat on an
    investigation that's already `verifying`/`completed`/`verification_failed`
    (409).
  - `POST /investigations/{id}/verify` now requires
    `StructuredCase.is_sufficient_for_verification()` to be true (400 if
    not) and rejects a concurrent re-run while one is already `verifying`
    (409) — previously it would happily run a near-empty verification on
    an incomplete case.
  - `POST /investigations/{id}/evidence` rejects an empty uploaded file and
    whitespace-only text evidence.
- **Timeout handling per external call** — see #5 above.
- **A health-check endpoint that actually pings dependencies** — `GET
  /health` now pings the database (`SELECT 1`) and does a real (free,
  keyless) call to the Hipo API to confirm outbound network access, plus
  reports which paid-provider keys are configured (without spending quota
  on them on every health check). Returns HTTP 503 if the DB is
  unreachable.
- **Alembic migration files** — `alembic/versions/` was completely empty
  (no migration had ever been generated). Hand-wrote
  `0001_initial_schema.py` to match `database/models.py` exactly. This
  could not be verified with `alembic autogenerate` against a live database
  (no network) — please run `alembic check` against a real DB before
  trusting it blindly in production.
- **A full mocked end-to-end pipeline test** —
  `tests/test_pipeline_e2e.py`. Runs the real FastAPI app (real routing,
  real Pydantic validation, real SQLAlchemy models, real
  aggregator/risk-engine/normalizer code) against a temporary SQLite file,
  with every external network call (Gemini, Groq, Tavily, Hipo,
  OpenSanctions) replaced by scripted responses. No live keys or network
  needed. The scenario is deliberately "obviously risky" (sanctioned agent,
  personal-wallet payment, visa-guarantee purpose, urgent deadline,
  mismatched program/amount in the uploaded evidence) so the test can
  assert the full pipeline reaches `risk_score=100`, `risk_level=VERY_HIGH`,
  `display_status=HIGH_RISK` end to end, plus a second test that the
  `/verify` input-validation guard actually rejects an incomplete case, and
  a third that `/health` reports correctly. **Not executed by me** — same
  network limitation as above; traced through by hand (see the worked
  arithmetic in the test file's docstring) and should pass.

## Minor cleanups

- `pytest.ini` (pre-existing) sets `asyncio_mode = auto`, but `pytest-asyncio`
  was never added to any requirements file, and no test file existed that
  needed it. Added `pytest-asyncio` to the new `requirements-dev.txt` so the
  existing config actually works, even though the new e2e test itself uses
  synchronous `TestClient` calls (no `async def test_...` needed for it).
- `research/hipo.py` had an unused `from config import settings` import —
  removed.
- `agents/investigator.py` built its prompt with Python's `repr()` of the
  conversation-history list instead of `json.dumps()` — harmless for pure
  ASCII but produces inconsistent quoting for the Urdu/Roman Urdu content
  this app is specifically built to handle. Fixed to use
  `json.dumps(..., ensure_ascii=False)`.
- Renamed `LLMClient._gemini`/`_groq` methods to `_gemini_call`/`_groq_call`
  to avoid reading confusingly similar to the module-level `_gemini`/`_groq`
  client singletons they call into (this was not a functional bug — Python
  resolved it correctly either way — just a readability fix while already
  touching this file for logging/timeouts).
- `main.py` now only auto-creates tables (`init_db()`) when
  `ENVIRONMENT` is `development`/`dev`/`local`/`test`; any other value logs
  that you should run `alembic upgrade head` instead, matching the
  docstring that was already there but not enforced.

## Explicitly NOT changed without asking you first

- The dual-parallel Tavily + Gemini research pattern — confirmed as
  designed, not touched.
- `data/hec_recognized.json` / `data/banned_agents.json` — confirmed empty,
  no fake entries invented.
- The exact emoji/display-status mapping — implemented as a clearly-labeled
  draft (`risk/display_status.py`) rather than silently guessed and shipped
  as if final. See the README's "Known genuine gaps" section.
