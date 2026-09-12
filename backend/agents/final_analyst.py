"""
Final safety analysis.

IMPORTANT DESIGN FIX vs. the original MVP: the original version asked the
LLM to generate the *entire* FinalReport, including `domains: list[DomainSummary]`
with each domain's full `evidence: list[EvidenceRecord]` reproduced by the
model itself. That undermines the product's core principle ("no single AI
opinion makes the final call - every conclusion is traceable to evidence,
and the AI only organizes/presents that evidence") in two ways:
  1. It has the LLM re-transcribe evidence it did not generate, risking
     dropped/altered/hallucinated fields inside a structured object whose
     correctness actually matters (source, authority, result enums, etc.).
  2. It's fragile: the Groq JSON-mode fallback is materially less reliable
     at deep nested-schema compliance than Gemini's schema-constrained
     decoding, so a Gemini outage could turn "narrative degraded" into
     "verification pipeline throws 502".

Fix: the LLM now only produces the parts that are genuinely its job -
plain-language fraud signals, a recommendation, and a safer next action.
Every domain's status/summary/evidence list is assembled here in Python,
directly from the deterministic aggregator output and the already-validated
EvidenceRecord objects. The LLM cannot invent or drop evidence because it
never sees the job of re-emitting it.
"""
import json
import logging

from pydantic import BaseModel, Field

from agents.llm_client import llm
from config import settings
from schemas.evidence import EvidenceRecord
from schemas.report import FinalReport, ManualCheck
from schemas.verification import DomainSummary

logger = logging.getLogger(__name__)

PROMPT = """You are the final safety analyst for VerifyAbroad-AI, a study-abroad safety assistant for Pakistani students.
Use ONLY the supplied structured case, evidence records, and domain statuses/summaries.
Never invent sources, facts, or verification outcomes, and never state a domain status different from the one supplied.
Do not call a person/company a scammer solely from weak evidence. Be explicit about uncertainty and contradictions.
The risk score is a risk indicator, not a probability - do not restate it as a percentage or certainty.
List concrete fraud signals actually present in the evidence (empty list if none).
Give a direct recommendation and exactly one concrete safer next action.
"""

DEFAULT_MANUAL_CHECKS = [
    ManualCheck(
        name="WHED — World Higher Education Database",
        url=settings.whed_url,
        reason="Search the university name independently as an additional manual institution check.",
    ),
    ManualCheck(
        name="SECP Pakistan — Company Name Search",
        url=settings.secp_search_url,
        reason="Check the agent/company name where relevant. Company registration does not prove university authorization.",
    ),
]


class LLMNarrative(BaseModel):
    """The only part of the final report the LLM is trusted to author."""
    fraud_signals: list[str] = Field(default_factory=list)
    recommendation: str
    safer_action: str


def _assemble_domains(
    all_records: list[EvidenceRecord], domain_statuses: dict[str, tuple[str, str]]
) -> list[DomainSummary]:
    """Deterministically builds each domain's status/summary/evidence -
    no LLM involvement, so evidence can never be dropped or altered here."""
    domains = []
    for domain_name, (status, summary) in domain_statuses.items():
        evidence = [
            r for r in all_records
            if (r.domain.value if hasattr(r.domain, "value") else str(r.domain)) == domain_name
        ]
        domains.append(
            DomainSummary(domain=domain_name, status=status, summary=summary, evidence=evidence)
        )
    return domains


async def generate_final_report(
    structured_case: dict,
    evidence_records: list[EvidenceRecord],
    domain_statuses: dict[str, tuple[str, str]],
    risk_score: int,
    risk_level: str,
) -> FinalReport:
    payload = {
        "structured_case": structured_case,
        "evidence_records": [r.model_dump(mode="json") for r in evidence_records],
        "domain_statuses": {k: {"status": v[0], "notes": v[1]} for k, v in domain_statuses.items()},
        "risk_score": risk_score,
        "risk_level": risk_level,
    }

    try:
        narrative = await llm.generate_json(PROMPT, json.dumps(payload, default=str), LLMNarrative)
    except Exception as exc:
        # The narrative is a convenience on top of deterministic data - if
        # both providers are down, degrade to a plain factual summary
        # instead of failing the whole verification run. The score, level,
        # and per-domain evidence are already known and don't depend on
        # this call succeeding.
        logger.error(
            "Final narrative generation failed (%s); falling back to a "
            "template-based narrative so the run still completes.", exc,
        )
        contradicted = [d for d, (s, _) in domain_statuses.items() if s == "CONTRADICTED"]
        narrative = LLMNarrative(
            fraud_signals=(
                [f"{d.capitalize()} verification returned CONTRADICTED." for d in contradicted]
                if contradicted else []
            ),
            recommendation=(
                "Automatic narrative generation is temporarily unavailable. "
                f"Based on the deterministic risk score ({risk_score}/100, {risk_level}), "
                "review the domain-by-domain evidence below carefully before proceeding."
            ),
            safer_action="Independently verify the university and agent using the manual-check links below before making any payment.",
        )

    return FinalReport(
        risk_level=risk_level,
        risk_score=risk_score,
        domains=_assemble_domains(evidence_records, domain_statuses),
        fraud_signals=narrative.fraud_signals,
        recommendation=narrative.recommendation,
        safer_action=narrative.safer_action,
        manual_checks=DEFAULT_MANUAL_CHECKS,
    )
