"""
Risk engine - pure deterministic scoring. No AI involved here by design:
this is application logic, not a probability estimate, and is presented to
the user as a risk indicator, not mathematical certainty.
"""
from schemas.evidence import EvidenceRecord, Domain

RULES = {
    "visa_guarantee_claim": 30,
    "unverified_agent": 25,
    "urgent_payment": 20,
    "personal_payment_account": 20,
    "institution_not_recognized": 25,
    "payment_process_mismatch": 25,
    "contradicted_program": 30,
    "contradictory_document": 20,
    "agent_banned_or_sanctioned": 35,
}


def compute_risk_score(records: list[EvidenceRecord], domain_statuses: dict[str, tuple[str, str]]) -> tuple[int, str]:
    score = 0

    # Institution
    if domain_statuses.get("institution", (None,))[0] == "CONTRADICTED":
        score += RULES["institution_not_recognized"]

    # Agent
    agent_status = domain_statuses.get("agent", (None,))[0]
    if agent_status in {"SUSPICIOUS", "UNVERIFIED"}:
        score += RULES["unverified_agent"]
    if agent_status == "CONTRADICTED":
        score += RULES["agent_banned_or_sanctioned"]

    # Payment
    payment_status = domain_statuses.get("payment", (None,))[0]
    if payment_status == "CONTRADICTED":
        score += RULES["personal_payment_account"]

    # Document / claims-based signals - scan claims text for known phrases.
    # NOTE: previously this checked for the literal substring "urgency",
    # but check_payment_deadline_urgency() (verification/document.py) only
    # ever emits the word "urgent" in its detail text, so this rule never
    # fired. Matching on "urgent" covers both "urgent" and "urgency".
    claim_texts = " ".join(r.claim.lower() + " " + (r.detail or "").lower() for r in records)
    if "visa guarantee" in claim_texts or "100% visa" in claim_texts:
        score += RULES["visa_guarantee_claim"]
    if "urgent" in claim_texts or "artificial urgency" in claim_texts:
        score += RULES["urgent_payment"]

    document_status = domain_statuses.get("document", (None,))[0]
    if document_status == "CONTRADICTED":
        score += RULES["contradictory_document"]

    # Program mismatch: the document-vs-case consistency check
    # (verification/document.py: cross_check_extracted_claims) emits a
    # "contradicted" record whose claim mentions "program" when the
    # evidence's stated program doesn't match what the student told the
    # investigator. This RULES entry existed but was never wired in.
    if any(
        r.result == "contradicted" and "program" in r.claim.lower()
        for r in records
    ):
        score += RULES["contradicted_program"]

    # Payment process mismatch: a document-vs-case consistency check that
    # specifically contradicts on payment (amount or method extracted from
    # the uploaded evidence doesn't match what the student stated). This is
    # distinct from personal_payment_account (a risky channel by itself) -
    # this is evidence the payment story itself doesn't line up.
    if any(
        r.result == "contradicted"
        and r.source_type == "consistency_rule"
        and (r.domain == Domain.payment or "payment" in r.claim.lower())
        for r in records
    ):
        score += RULES["payment_process_mismatch"]

    score = min(score, 100)

    if score < 30:
        level = "LOW"
    elif score < 60:
        level = "MEDIUM"
    elif score < 80:
        level = "HIGH"
    else:
        level = "VERY_HIGH"

    return score, level
