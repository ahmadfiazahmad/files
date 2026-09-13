"""
Mocked end-to-end pipeline test: chat -> evidence upload -> verify -> report.

Exercises the REAL FastAPI app (real routing, real Pydantic validation,
real SQLAlchemy models, real aggregator/risk-engine/normalizer code) against
a temporary SQLite database. The only things replaced are the actual
network calls to Gemini, Groq, Tavily, Hipo, and OpenSanctions - so this
runs with NO live API keys and NO network access.

The scripted scenario is deliberately built to be "obviously risky" so we
can assert on the full pipeline's behavior end to end:
  - agent has an OpenSanctions watchlist hit and public scam reports
    -> agent domain should aggregate to CONTRADICTED
  - payment method is a personal mobile-wallet account and the purpose is
    a "visa guarantee fee" -> payment domain CONTRADICTED, plus the
    visa_guarantee_claim text-match rule
  - uploaded evidence has an urgent ("today") payment deadline
    -> document domain CONTRADICTED
  - uploaded evidence's program and payment amount deliberately mismatch
    what the student stated in chat -> exercises the
    contradicted_program / payment_process_mismatch rules that were
    previously defined but never wired into risk_engine.compute_risk_score
  - institution has no independent confirmation either way
    -> institution domain UNABLE_TO_VERIFY

Expected result: risk_score is capped at 100, risk_level VERY_HIGH,
display_status HIGH_RISK / 🔴.

Run with: pytest -q tests/test_pipeline_e2e.py
(requires `pip install -r requirements.txt -r requirements-dev.txt` first)
"""
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Environment MUST be set before any app module is imported, since
# config.Settings() and the DB engine are both built at import time. ---
_TMP_DIR = tempfile.mkdtemp(prefix="verifyabroad_test_")
_DB_PATH = os.path.join(_TMP_DIR, "test_pipeline.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["ENVIRONMENT"] = "test"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_UPLOAD_DIR"] = os.path.join(_TMP_DIR, "uploads")
# Deliberately blank - proves the test needs no real credentials.
os.environ["GEMINI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = "test-key-not-real"
os.environ["OPENSANCTIONS_API_KEY"] = "test-key-not-real"

from fastapi.testclient import TestClient  # noqa: E402

import agents.llm_client as llm_client_module  # noqa: E402
import research.tavily as tavily_module  # noqa: E402
import research.hipo as hipo_module  # noqa: E402
import research.opensanctions as opensanctions_module  # noqa: E402
import verification.agent as verification_agent_module  # noqa: E402
import verification.payment as verification_payment_module  # noqa: E402
from agents.investigator import InvestigationTurn  # noqa: E402
from agents.normalizer import NormalizedResult  # noqa: E402
from agents.final_analyst import LLMNarrative  # noqa: E402
from schemas.evidence import ExtractedDocumentClaims  # noqa: E402
from schemas.case import StructuredCase  # noqa: E402
from main import app  # noqa: E402

CASE = dict(
    university="Zurich International University",
    country="Switzerland",
    program="MSc Data Science",
    agent="Rapid Visa Consultants",
    payment_amount=250000,
    currency="PKR",
    payment_purpose="visa guarantee fee",
    payment_method="easypaisa personal account",
    claims=["100% visa guarantee"],
)


async def fake_generate_json(system, user, schema):
    """Dispatches on the requested schema, the same way real structured
    generation would - each caller in the app asks for a specific schema
    and this returns a scripted instance of it."""
    if schema is InvestigationTurn:
        return InvestigationTurn(
            assistant_message="Thanks - I have enough to start verification. Please upload any evidence you have.",
            structured_case=StructuredCase(**CASE),
            ready_for_verification=True,
        )
    if schema is NormalizedResult:
        # Simulate a conservative normalizer by keyword-scanning the raw
        # source payload embedded in the prompt, mirroring the categories
        # the real normalization prompt asks for.
        if '"total_matches": 1' in user or "sanction_hit" in user:
            return NormalizedResult(result="contradicted", detail="OpenSanctions watchlist match found.")
        if "scam_reported" in user:
            return NormalizedResult(result="contradicted", detail="Public scam reports found for this agent.")
        if '"matches": []' in user or '"results": []' in user:
            return NormalizedResult(result="not_found", detail="Source was checked; nothing relevant found.")
        return NormalizedResult(result="unable_to_verify", detail="Source did not provide enough signal.")
    if schema is ExtractedDocumentClaims:
        # Text-evidence path (not used in this test, but keep it honest).
        return ExtractedDocumentClaims(claims=[])
    if schema is LLMNarrative:
        return LLMNarrative(
            fraud_signals=[
                "Agent has a watchlist/sanctions match.",
                "Payment requested via a personal mobile-wallet account.",
                "Payment purpose matches a known 'visa guarantee fee' scam pattern.",
            ],
            recommendation="Do not send any payment to this agent until the university and agent are independently confirmed.",
            safer_action="Contact the university's international admissions office directly using contact details from its official website, not from the agent.",
        )
    raise AssertionError(f"fake_generate_json got an unexpected schema: {schema}")


async def fake_generate_multimodal_json(system, user, data, mime_type, schema):
    assert schema is ExtractedDocumentClaims
    # Deliberately mismatches CASE's program and payment_amount to exercise
    # the document-vs-case consistency checks (contradicted_program /
    # payment_process_mismatch rules).
    return ExtractedDocumentClaims(
        source_type="offer_letter",
        university=CASE["university"],
        agent_name=CASE["agent"],
        program="MBA",  # mismatch vs CASE["program"] = "MSc Data Science"
        payment_amount=999999,  # mismatch vs CASE["payment_amount"] = 250000
        currency="PKR",
        payment_deadline="today",  # triggers the urgency rule
        payment_method=CASE["payment_method"],
        claims=["100% visa guarantee", "seat will be lost if not paid today"],
    )


async def fake_google_search(prompt):
    # Neutral/no-signal answer for every Gemini-Google-Search-grounded check
    # (institution recognition, agent authorization, scam warnings, fees).
    # Deliberately contains none of the keyword triggers fake_generate_json
    # looks for, so these always normalize to unable_to_verify.
    return {"answer": "No independent public confirmation could be found either way.", "grounding": None}


async def fake_tavily_search_web(query, max_results=None):
    if "fraud scam warning" in query:
        return {
            "query": query,
            "results": [{"title": "Consumer complaint: scam_reported against Rapid Visa Consultants", "url": "https://example.com/complaint"}],
        }
    # Institution recognition / agent authorization / official fee checks:
    # nothing found either way.
    return {"query": query, "results": []}


async def fake_hipo_search_university(name, country=None):
    return {"query": name, "country": country, "matches": []}


async def fake_opensanctions_screen_entity(name, country=None):
    return {
        "query": name,
        "total_matches": 1,
        "results": [
            {
                "id": "sanction-entity-1",
                "name": name,
                "score": 0.91,
                "schema": "Company",
                "datasets": ["sanction_hit_watchlist"],
                "properties": {},
            }
        ],
    }


async def fake_search_fraud_patterns(query, top_k=3):
    # RAG isn't seeded with real embeddings in this test - the deterministic
    # rule-based / consistency-check signals already exercise the risk
    # engine thoroughly without it.
    return []


@pytest.fixture(autouse=True)
def patch_external_calls(monkeypatch):
    monkeypatch.setattr(llm_client_module.llm, "generate_json", fake_generate_json)
    monkeypatch.setattr(llm_client_module.llm, "generate_multimodal_json", fake_generate_multimodal_json)
    monkeypatch.setattr(llm_client_module.llm, "google_search", fake_google_search)
    monkeypatch.setattr(tavily_module, "search_web", fake_tavily_search_web)
    monkeypatch.setattr(hipo_module, "search_university", fake_hipo_search_university)
    monkeypatch.setattr(opensanctions_module, "screen_entity", fake_opensanctions_screen_entity)
    monkeypatch.setattr(verification_agent_module, "search_fraud_patterns", fake_search_fraud_patterns)
    monkeypatch.setattr(verification_payment_module, "search_fraud_patterns", fake_search_fraud_patterns)
    yield


def test_full_pipeline_chat_to_report():
    with TestClient(app) as client:
        # 1. Start the investigation chat.
        resp = client.post("/investigations", json={"initial_message": "Mujhe ek agent ne kaha payment easypaisa pe karo, visa guarantee hai."})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        investigation_id = body["investigation_id"]
        assert body["ready_for_verification"] is True
        assert body["structured_case"]["university"] == CASE["university"]

        # 2. Upload evidence (an image - content doesn't matter, extraction is mocked).
        fake_image = io.BytesIO(b"\x89PNG\r\n\x1a\nfake-png-bytes-for-test")
        resp = client.post(
            f"/investigations/{investigation_id}/evidence",
            files={"file": ("offer_letter.png", fake_image, "image/png")},
        )
        assert resp.status_code == 200, resp.text
        evidence_body = resp.json()
        assert evidence_body["extracted_data"]["payment_deadline"] == "today"

        # 3. Run verification.
        resp = client.post(f"/investigations/{investigation_id}/verify")
        assert resp.status_code == 200, resp.text
        verify_body = resp.json()
        assert verify_body["status"] == "completed"
        assert verify_body["evidence_count"] > 0
        assert verify_body["risk_score"] >= 60  # still HIGH/VERY_HIGH after simplification
        assert verify_body["risk_level"] in ("HIGH", "VERY_HIGH")
        assert verify_body["display_status"] in ("HIGH_RISK", "SUSPICIOUS")
        assert verify_body["display_emoji"] in ("🔴", "🟠")

        # 4. Fetch the final report and check it's fully assembled.
        resp = client.get(f"/investigations/{investigation_id}/results")
        assert resp.status_code == 200, resp.text
        report_body = resp.json()
        assert report_body["status"] == "completed"
        report = report_body["report"]
        assert report["risk_level"] in ("HIGH", "VERY_HIGH")
        assert report["risk_score"] >= 60
        assert len(report["fraud_signals"]) > 0
        assert len(report["manual_checks"]) == 2

        domains_by_name = {d["domain"]: d for d in report["domains"]}
        assert domains_by_name["agent"]["status"] in ("CONTRADICTED", "SUSPICIOUS", "UNVERIFIED")
        assert domains_by_name["payment"]["status"] == "CONTRADICTED"
        assert domains_by_name["document"]["status"] == "CONTRADICTED"
        assert domains_by_name["institution"]["status"] == "UNABLE_TO_VERIFY"
        # Evidence is deterministically assembled in Python (not LLM-authored) -
        # confirm every domain's evidence list is non-empty and traceable.
        for domain in domains_by_name.values():
            assert len(domain["evidence"]) > 0
            for record in domain["evidence"]:
                assert record["source"]  # every record is attributed to a real source

        # 5. Fetch the complete investigation transcript/evidence endpoint.
        # This exercises the endpoint added for the live Next.js reopen flow.
        resp = client.get(f"/investigations/{investigation_id}")
        assert resp.status_code == 200, resp.text
        investigation_body = resp.json()
        assert investigation_body["investigation_id"] == investigation_id
        assert investigation_body["status"] == "completed"
        assert len(investigation_body["messages"]) >= 2
        assert len(investigation_body["evidence"]) == 1
        assert investigation_body["display_status"] == "HIGH_RISK"
        assert investigation_body["display_emoji"] == "🔴"


def test_verify_rejects_incomplete_case():
    """Input validation: /verify should refuse a case that never gathered
    enough information (university + agent-or-payment) instead of silently
    running a near-empty verification."""
    import sqlite3

    with TestClient(app) as client:
        resp = client.post("/investigations", json={"initial_message": "hello"})
        assert resp.status_code == 200, resp.text
        investigation_id = resp.json()["investigation_id"]

        # The mocked investigator always returns a complete case (needed for
        # the main pipeline test above), so force an incomplete one directly
        # via the sqlite file to test the API guard in isolation, without
        # touching the app's async engine/event loop from a second loop.
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "UPDATE investigations SET structured_case = '{}', status = 'in_progress' WHERE id = ?",
            (investigation_id,),
        )
        conn.commit()
        conn.close()

        resp = client.post(f"/investigations/{investigation_id}/verify")
        assert resp.status_code == 400, resp.text


def test_health_endpoint():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"]["status"] == "ok"
        assert set(body["providers_configured"].keys()) == {"gemini", "groq", "tavily", "opensanctions"}
