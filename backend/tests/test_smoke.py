"""Fast local smoke test for the deterministic core (no external API keys needed)."""
import sys
sys.path.insert(0, ".")

from schemas.evidence import Domain, AuthorityLevel, VerificationResult, EvidenceRecord
from risk.aggregator import aggregate_all
from risk.risk_engine import compute_risk_score


def main():
    records = [
        EvidenceRecord(
            domain=Domain.institution,
            claim="University is recognized",
            source="Official test source",
            source_type="test",
            authority=AuthorityLevel.high,
            result=VerificationResult.verified,
            detail="Confirmed for smoke test.",
        ),
        EvidenceRecord(
            domain=Domain.agent,
            claim="Agent is an authorized representative",
            source="Official test source",
            source_type="test",
            authority=AuthorityLevel.high,
            result=VerificationResult.contradicted,
            detail="Agent not listed.",
        ),
        EvidenceRecord(
            domain=Domain.payment,
            claim="Personal account payment requested",
            source="Application rule logic",
            source_type="rule_logic",
            authority=AuthorityLevel.high,
            result=VerificationResult.contradicted,
            detail="Risky payment channel.",
        ),
        EvidenceRecord(
            domain=Domain.document,
            claim="100% visa guarantee",
            source="Fraud-pattern RAG",
            source_type="rag_pattern",
            authority=AuthorityLevel.medium,
            result=VerificationResult.claimed,
            detail="Known fraud-pattern match.",
        ),
    ]

    statuses = aggregate_all(records)
    score, level = compute_risk_score(records, statuses)

    assert statuses["institution"][0] == "VERIFIED"
    assert statuses["agent"][0] == "CONTRADICTED"
    assert statuses["payment"][0] == "CONTRADICTED"
    assert score >= 60
    assert level in {"HIGH", "VERY_HIGH"}
    print(f"[PASS] deterministic smoke test: {score}/100 {level}")


if __name__ == "__main__":
    main()
