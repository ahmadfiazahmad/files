import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EvidenceItem, EvidenceRecord as EvidenceRecordModel, Investigation, Message
from database.session import get_db
from schemas.case import StructuredCase
from schemas.verification import VerificationRunResponse
from simple_verifier import run_simple_verification
from risk.display_status import derive_display_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/investigations", tags=["verification"])


@router.post("/{investigation_id}/verify", response_model=VerificationRunResponse)
async def run_verification(investigation_id: str, db: AsyncSession = Depends(get_db)):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    case = StructuredCase(**(investigation.structured_case or {}))
    evidence_result = await db.execute(
        select(EvidenceItem)
        .where(EvidenceItem.investigation_id == investigation_id)
        .order_by(EvidenceItem.created_at.desc())
    )
    evidence_items = list(evidence_result.scalars().all())

    last_message_result = await db.execute(
        select(Message)
        .where(Message.investigation_id == investigation_id)
        .order_by(Message.created_at.desc())
    )
    latest = last_message_result.scalars().first()
    raw_message = latest.content if latest else json_fallback_case(case)

    try:
        report = await run_simple_verification(case, raw_message, evidence_items)
    except Exception as exc:
        logger.error("Simple verification failed: %s", exc, exc_info=True)
        investigation.status = "verification_failed"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Verification pipeline failed: {exc}") from exc

    await db.execute(delete(EvidenceRecordModel).where(EvidenceRecordModel.investigation_id == investigation_id))
    for domain in report.domains:
        for evidence in domain.evidence:
            db.add(EvidenceRecordModel(
                investigation_id=investigation_id,
                domain=evidence.domain.value,
                claim=evidence.claim,
                source=evidence.source,
                source_type=evidence.source_type,
                authority=evidence.authority.value,
                result=evidence.result.value,
                detail=evidence.detail,
                raw_response=evidence.raw_response,
            ))
    investigation.risk_score = report.risk_score
    investigation.risk_level = report.risk_level
    investigation.final_report = report.model_dump(mode="json")
    investigation.status = "completed"
    await db.commit()

    domain_statuses = {d.domain: (d.status, d.summary) for d in report.domains}
    display_status, display_emoji = derive_display_status(report.risk_level, domain_statuses)
    evidence_count = sum(len(d.evidence) for d in report.domains)
    return VerificationRunResponse(
        investigation_id=investigation.id,
        status="completed",
        evidence_count=evidence_count,
        risk_score=report.risk_score,
        risk_level=report.risk_level,
        display_status=display_status,
        display_emoji=display_emoji,
    )


def json_fallback_case(case: StructuredCase) -> str:
    return "Verify this study-abroad case: " + case.model_dump_json()
