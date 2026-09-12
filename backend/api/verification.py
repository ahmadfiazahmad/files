import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

from database.session import get_db
from database.models import Investigation, EvidenceRecord as EvidenceRecordModel, EvidenceItem
from schemas.case import StructuredCase
from schemas.verification import VerificationRunResponse
from verification.institution import verify_institution
from verification.agent import verify_agent
from verification.payment import verify_payment
from verification.document import check_payment_deadline_urgency, check_intake_date_validity, cross_check_extracted_claims
from risk.aggregator import aggregate_all
from risk.risk_engine import compute_risk_score
from risk.display_status import derive_display_status
from agents.final_analyst import generate_final_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investigations", tags=["verification"])


@router.post("/{investigation_id}/verify", response_model=VerificationRunResponse)
async def run_verification(investigation_id: str, db: AsyncSession = Depends(get_db)):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    if investigation.status == "verifying":
        raise HTTPException(
            status_code=409,
            detail="A verification run is already in progress for this investigation.",
        )

    case = StructuredCase(**investigation.structured_case)
    if not case.is_sufficient_for_verification():
        raise HTTPException(
            status_code=400,
            detail=(
                "This case doesn't have enough information yet to verify "
                "(need at least university plus either agent or payment "
                "information). Continue the investigation chat first."
            ),
        )

    investigation.status = "verifying"
    await db.commit()

    result = await db.execute(
        select(EvidenceItem)
        .where(EvidenceItem.investigation_id == investigation_id)
        .order_by(EvidenceItem.created_at.desc())
    )
    evidence_items = list(result.scalars().all())
    latest = evidence_items[0].extracted_data if evidence_items else {}

    try:
        institution_task = verify_institution(case.university, case.country)
        agent_task = verify_agent(case.agent, case.university, case.country)
        payment_task = verify_payment(
            case.university, case.program, case.country,
            case.payment_method, case.payment_purpose
        )
        institution_records, agent_records, payment_records = await asyncio.gather(
            institution_task, agent_task, payment_task
        )

        document_records = []
        if latest:
            document_records.extend([
                check_payment_deadline_urgency(latest.get("payment_deadline")),
                check_intake_date_validity(latest.get("intake")),
            ])
        domain_precheck = aggregate_all([*institution_records, *agent_records, *payment_records])
        if latest:
            document_records.extend(cross_check_extracted_claims(latest, case, domain_precheck))

        all_records = [*institution_records, *agent_records, *payment_records, *document_records]

        for r in all_records:
            db.add(EvidenceRecordModel(
                investigation_id=investigation_id,
                domain=r.domain.value,
                claim=r.claim,
                source=r.source,
                source_type=r.source_type,
                authority=r.authority.value,
                result=r.result.value,
                detail=r.detail,
                raw_response=r.raw_response,
            ))

        domain_statuses = aggregate_all(all_records)
        risk_score, risk_level = compute_risk_score(all_records, domain_statuses)
        final_report = await generate_final_report(
            case.model_dump(), all_records, domain_statuses, risk_score, risk_level
        )

        investigation.risk_score = risk_score
        investigation.risk_level = risk_level
        investigation.final_report = final_report.model_dump(mode="json")
        investigation.status = "completed"
        await db.commit()

    except Exception as exc:
        logger.error(
            "Verification pipeline failed for investigation_id=%s: %s",
            investigation_id, exc, exc_info=True,
        )
        investigation.status = "verification_failed"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Verification pipeline failed: {exc}") from exc

    display_status, display_emoji = derive_display_status(risk_level, domain_statuses)

    return VerificationRunResponse(
        investigation_id=investigation_id,
        status="completed",
        evidence_count=len(all_records),
        risk_score=risk_score,
        risk_level=risk_level,
        display_status=display_status,
        display_emoji=display_emoji,
    )
