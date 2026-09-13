"""Simple, hackathon-first verification flow.

Purpose: keep the existing FastAPI contracts but remove the chat-loop behavior.
Every user message is treated as information, not as a prompt to ask another
question. The backend extracts what it can, performs a small number of Tavily
searches, asks Gemini for a structured assessment with Groq fallback, and
stores the result in SQLite.
"""

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from agents.llm_client import llm
from schemas.case import StructuredCase
from schemas.evidence import AuthorityLevel, Domain, EvidenceRecord, VerificationResult
from schemas.report import FinalReport, ManualCheck
from schemas.verification import DomainSummary
from research.tavily import search_web

logger = logging.getLogger(__name__)


class ExtractedCase(BaseModel):
    university: str | None = None
    country: str | None = None
    program: str | None = None
    agent: str | None = None
    payment_amount: float | None = None
    currency: str | None = None
    payment_purpose: str | None = None
    payment_method: str | None = None
    degree_level: str | None = None
    funding_type: str | None = None
    scholarship: str | None = None
    claims: list[str] = Field(default_factory=list)


class DomainAssessment(BaseModel):
    domain: str
    status: str
    summary: str


class SimpleAssessment(BaseModel):
    risk_level: str = "MEDIUM"
    risk_score: int = Field(default=50, ge=0, le=100)
    domains: list[DomainAssessment] = Field(default_factory=list)
    fraud_signals: list[str] = Field(default_factory=list)
    recommendation: str
    safer_action: str


EXTRACT_PROMPT = """Extract study-abroad verification facts from the student's message.
Return ONLY facts explicitly present. Do not ask questions and do not invent data.
The user may write English, Urdu, or Roman Urdu.
"""

ASSESS_PROMPT = """You are VerifyAbroad-AI's final safety analyst for a hackathon MVP.
Assess the student's study-abroad scenario using the supplied case, uploaded evidence,
and live web-search snippets. Produce a concise, professional safety assessment.
Do NOT claim certainty when evidence is missing. Distinguish verified, unverified,
and suspicious/contradicted information.
Risk score is an indicator, not proof of fraud.
Keep recommendation and safer_action practical and student-friendly.
"""

DOMAIN_ALIASES = {
    "institution": Domain.institution,
    "university": Domain.institution,
    "agent": Domain.agent,
    "consultant": Domain.agent,
    "payment": Domain.payment,
    "document": Domain.document,
    "offer": Domain.document,
}


def _merge_case(current: StructuredCase, extracted: ExtractedCase) -> StructuredCase:
    data = current.model_dump()
    for field in (
        "university", "country", "program", "agent", "payment_amount", "currency",
        "payment_purpose", "payment_method", "degree_level", "funding_type", "scholarship",
    ):
        value = getattr(extracted, field)
        if value not in (None, ""):
            data[field] = value
    merged_claims = list(data.get("claims") or [])
    for claim in extracted.claims:
        if claim and claim not in merged_claims:
            merged_claims.append(claim)
    data["claims"] = merged_claims[-12:]
    return StructuredCase(**data)


def _fallback_extract(text: str, current: StructuredCase) -> StructuredCase:
    # Conservative fallback when both LLMs are unavailable: keep the current
    # case and at least preserve the raw user statement as a claim.
    data = current.model_dump()
    if text.strip():
        claims = list(data.get("claims") or [])
        if text.strip() not in claims:
            claims.append(text.strip())
        data["claims"] = claims[-12:]
    return StructuredCase(**data)


async def extract_and_merge_case(message: str, current: StructuredCase) -> StructuredCase:
    if not message.strip():
        return current
    try:
        extracted = await llm.generate_json(
            EXTRACT_PROMPT,
            f"Current case:\n{current.model_dump_json()}\n\nNew student message:\n{message}",
            ExtractedCase,
        )
        return _merge_case(current, extracted)
    except Exception as exc:
        logger.warning("Case extraction unavailable; using conservative fallback: %s", exc)
        return _fallback_extract(message, current)


def _query_plan(case: StructuredCase, raw_message: str) -> list[tuple[str, Domain]]:
    queries: list[tuple[str, Domain]] = []
    if case.university:
        queries.append((
            f'"{case.university}" official recognition admissions {case.country or "international students"}',
            Domain.institution,
        ))
    if case.agent:
        queries.append((
            f'"{case.agent}" study abroad scam fraud Pakistan {case.university or ""}'.strip(),
            Domain.agent,
        ))
    payment_text = " ".join(x for x in [case.payment_purpose, case.payment_method, case.program] if x)
    if case.university and payment_text:
        queries.append((
            f'"{case.university}" official tuition payment policy {payment_text}',
            Domain.payment,
        ))
    if not queries:
        queries.append((raw_message[:500], Domain.document))
    return queries[:3]


def _search_context(results: list[dict]) -> str:
    compact: list[dict[str, Any]] = []
    for item in results:
        compact.append({
            "query": item.get("query"),
            "error": item.get("error"),
            "results": [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "content": (r.get("content") or r.get("raw_content") or "")[:1200],
                }
                for r in (item.get("results") or [])[:5]
            ],
        })
    return json.dumps(compact, ensure_ascii=False)


def _make_tavily_records(searches: list[tuple[str, Domain]], results: list[dict]) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for (query, domain), payload in zip(searches, results):
        raw_results = payload.get("results") or []
        if not raw_results:
            records.append(EvidenceRecord(
                domain=domain,
                claim=query,
                source="Tavily live web research",
                source_type="tavily_web",
                authority=AuthorityLevel.high,
                result=VerificationResult.unable_to_verify,
                detail=payload.get("error") or "No relevant live-web results were returned.",
                raw_response=payload,
            ))
            continue
        # One evidence record per search query keeps the database small while
        # retaining the URLs the student can inspect in the report.
        links = [r.get("url") for r in raw_results[:4] if r.get("url")]
        titles = [r.get("title") for r in raw_results[:4] if r.get("title")]
        records.append(EvidenceRecord(
            domain=domain,
            claim=query,
            source="Tavily live web research",
            source_type="tavily_web",
            authority=AuthorityLevel.high,
            result=VerificationResult.claimed,
            detail="Live search found: " + "; ".join(titles[:4]) + (" | URLs: " + ", ".join(links[:4]) if links else ""),
            raw_response={"query": query, "results": raw_results[:4]},
        ))
    return records


def _manual_checks() -> list[ManualCheck]:
    return [
        ManualCheck(
            name="Official university website",
            url="https://www.gov.uk/check-uk-university",
            reason="Confirm the institution, program and payment instructions independently on the official source.",
        ),
        ManualCheck(
            name="Pakistan HEC",
            url="https://hec.gov.pk/",
            reason="Check recognition where applicable for a Pakistani student.",
        ),
    ]


async def run_simple_verification(
    case: StructuredCase,
    raw_message: str,
    evidence_items: list[Any] | None = None,
) -> FinalReport:
    searches = _query_plan(case, raw_message)
    search_results = await asyncio.gather(*(search_web(q) for q, _ in searches), return_exceptions=True)
    normalized_results: list[dict] = []
    for result in search_results:
        if isinstance(result, Exception):
            normalized_results.append({"error": str(result), "results": []})
        else:
            normalized_results.append(result)

    evidence_payload = []
    for item in evidence_items or []:
        evidence_payload.append({
            "type": item.evidence_type,
            "extracted": item.extracted_data or {},
            "text": (item.raw_text or "")[:2500],
        })

    prompt = (
        f"Student case:\n{case.model_dump_json()}\n\n"
        f"Original/latest message:\n{raw_message}\n\n"
        f"Uploaded evidence:\n{json.dumps(evidence_payload, ensure_ascii=False)}\n\n"
        f"Tavily live-search results:\n{_search_context(normalized_results)}\n\n"
        "Return a verdict covering these domains where relevant: institution, agent, payment, document."
    )

    try:
        assessment = await llm.generate_json(ASSESS_PROMPT, prompt, SimpleAssessment)
    except Exception as exc:
        logger.error("Simple assessment failed; using deterministic fallback: %s", exc)
        assessment = SimpleAssessment(
            risk_level="MEDIUM",
            risk_score=50,
            domains=[
                DomainAssessment(domain=d.value, status="UNVERIFIED", summary="Live evidence was gathered, but an AI verdict was unavailable.")
                for _, d in searches
            ] or [DomainAssessment(domain="document", status="UNVERIFIED", summary="No reliable domain-specific verdict was available.")],
            fraud_signals=[],
            recommendation="Do not pay until the university, agent and payment instructions are independently confirmed.",
            safer_action="Use the official university website or other authoritative source to confirm the details before paying.",
        )

    # Build traceable domain summaries from the LLM's compact assessment + Tavily records.
    tavily_records = _make_tavily_records(searches, normalized_results)
    by_domain: dict[str, list[EvidenceRecord]] = {}
    for record in tavily_records:
        by_domain.setdefault(record.domain.value, []).append(record)

    domains: list[DomainSummary] = []
    seen: set[str] = set()
    for item in assessment.domains:
        key = item.domain.lower()
        domain = DOMAIN_ALIASES.get(key, Domain.document).value
        if domain in seen:
            continue
        seen.add(domain)
        domains.append(DomainSummary(
            domain=domain,
            status=item.status.upper(),
            summary=item.summary,
            evidence=by_domain.get(domain, []),
        ))
    for _, domain in searches:
        key = domain.value
        if key not in seen:
            seen.add(key)
            domains.append(DomainSummary(
                domain=key,
                status="UNVERIFIED",
                summary="Live web evidence was gathered; independent confirmation remains necessary.",
                evidence=by_domain.get(key, []),
            ))

    # Uploaded evidence is represented in the document domain without needing
    # another LLM call. This makes the demo show that evidence was actually used.
    if evidence_items:
        existing = next((d for d in domains if d.domain == Domain.document.value), None)
        if existing:
            existing.evidence.extend([
                EvidenceRecord(
                    domain=Domain.document,
                    claim=f"Uploaded {item.evidence_type} evidence was analyzed.",
                    source="Student-provided evidence",
                    source_type="uploaded_evidence",
                    authority=AuthorityLevel.medium,
                    result=VerificationResult.claimed,
                    detail=(item.extracted_data or {}).get("claims", ["Evidence content extracted for review."])[0] if isinstance((item.extracted_data or {}).get("claims"), list) else "Evidence content extracted for review.",
                )
                for item in evidence_items
            ])
        else:
            domains.append(DomainSummary(
                domain="document",
                status="UNVERIFIED",
                summary="Student-provided evidence was included in the assessment.",
                evidence=[EvidenceRecord(
                    domain=Domain.document,
                    claim=f"Uploaded {item.evidence_type} evidence was analyzed.",
                    source="Student-provided evidence",
                    source_type="uploaded_evidence",
                    authority=AuthorityLevel.medium,
                    result=VerificationResult.claimed,
                    detail="Evidence content extracted for review.",
                ) for item in evidence_items],
            ))

    return FinalReport(
        risk_level=assessment.risk_level.upper(),
        risk_score=max(0, min(100, assessment.risk_score)),
        domains=domains,
        fraud_signals=assessment.fraud_signals[:6],
        recommendation=assessment.recommendation,
        safer_action=assessment.safer_action,
        manual_checks=_manual_checks(),
    )
