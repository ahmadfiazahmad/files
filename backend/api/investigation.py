"""Simple hackathon investigation API: collect information, verify, report."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EvidenceItem, EvidenceRecord as EvidenceRecordModel, Investigation, Message
from database.session import get_db
from schemas.case import (
    ContextUpdateRequest, EvidenceItemSummary, InvestigationCreateRequest,
    InvestigationCreateResponse, InvestigationResponse, MessageRecord,
    MessageRequest, MessageResponse, StructuredCase,
)
from schemas.report import FinalReport
from risk.display_status import derive_display_status
from simple_verifier import extract_and_merge_case, run_simple_verification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/investigations", tags=["investigation"])


def _chat_report(report: FinalReport) -> str:
    level = report.risk_level.upper()
    verdict = {
        "LOW": "LOW RISK / NO OBVIOUS RED FLAGS FOUND",
        "MEDIUM": "CAUTION / SOME DETAILS NEED CONFIRMATION",
        "HIGH": "HIGH RISK / MULTIPLE RED FLAGS FOUND",
        "VERY_HIGH": "VERY HIGH RISK / STRONG FRAUD SIGNALS FOUND",
    }.get(level, f"{level} RISK")
    lines = [
        f"**Verification result: {verdict}** — risk score {report.risk_score}/100.",
        report.recommendation,
    ]
    if report.fraud_signals:
        lines.append("Red flags: " + "; ".join(report.fraud_signals[:3]))
    lines.append("Next step: " + report.safer_action)
    return "\n\n".join(lines)


async def _save_report(investigation: Investigation, db: AsyncSession, raw_message: str) -> str:
    case = StructuredCase(**(investigation.structured_case or {}))
    result = await db.execute(
        select(EvidenceItem)
        .where(EvidenceItem.investigation_id == investigation.id)
        .order_by(EvidenceItem.created_at.desc())
    )
    evidence_items = list(result.scalars().all())
    report = await run_simple_verification(case, raw_message, evidence_items)

    investigation.risk_score = report.risk_score
    investigation.risk_level = report.risk_level
    investigation.final_report = report.model_dump(mode="json")
    investigation.status = "completed"
    return _chat_report(report)


@router.post("", response_model=InvestigationCreateResponse)
async def create_investigation(payload: InvestigationCreateRequest, db: AsyncSession = Depends(get_db)):
    if not payload.initial_message or not payload.initial_message.strip():
        raise HTTPException(status_code=400, detail="initial_message must not be empty")

    investigation = Investigation(structured_case={})
    db.add(investigation)
    await db.flush()
    db.add(Message(investigation_id=investigation.id, role="user", content=payload.initial_message))

    try:
        case = await extract_and_merge_case(payload.initial_message, StructuredCase())
        investigation.structured_case = case.model_dump()
        assistant_message = await _save_report(investigation, db, payload.initial_message)
        db.add(Message(investigation_id=investigation.id, role="assistant", content=assistant_message))
        await db.commit()
    except Exception as exc:
        logger.error("Simple investigation failed: %s", exc, exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Investigation assistant is temporarily unavailable: {exc}") from exc

    return InvestigationCreateResponse(
        investigation_id=investigation.id,
        assistant_message=assistant_message,
        structured_case=StructuredCase(**investigation.structured_case),
        ready_for_verification=True,
    )


@router.post("/{investigation_id}/messages", response_model=MessageResponse)
async def continue_investigation(investigation_id: str, payload: MessageRequest, db: AsyncSession = Depends(get_db)):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    current = StructuredCase(**(investigation.structured_case or {}))
    db.add(Message(investigation_id=investigation_id, role="user", content=payload.message))
    try:
        updated = await extract_and_merge_case(payload.message, current)
        investigation.structured_case = updated.model_dump()
        assistant_message = await _save_report(investigation, db, payload.message)
        db.add(Message(investigation_id=investigation_id, role="assistant", content=assistant_message))
        await db.commit()
    except Exception as exc:
        logger.error("Simple follow-up verification failed: %s", exc, exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Verification assistant is temporarily unavailable: {exc}") from exc

    return MessageResponse(
        assistant_message=assistant_message,
        structured_case=updated,
        ready_for_verification=True,
    )


@router.get("/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(investigation_id: str, db: AsyncSession = Depends(get_db)):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    messages_result = await db.execute(select(Message).where(Message.investigation_id == investigation_id).order_by(Message.created_at))
    messages = [MessageRecord(id=m.id, role=m.role, content=m.content, created_at=m.created_at.isoformat()) for m in messages_result.scalars().all()]

    evidence_result = await db.execute(select(EvidenceItem).where(EvidenceItem.investigation_id == investigation_id).order_by(EvidenceItem.created_at))
    evidence = []
    for item in evidence_result.scalars().all():
        label = Path(item.file_path).name if item.file_path else "Pasted evidence"
        mime = "application/pdf" if item.evidence_type == "document" else None
        evidence.append(EvidenceItemSummary(
            id=item.id, evidence_type=item.evidence_type, label=label, mime=mime,
            size_bytes=None, created_at=item.created_at.isoformat(),
        ))

    report = FinalReport(**investigation.final_report) if investigation.final_report else None
    display_status, display_emoji = (None, None)
    if report is not None:
        domain_statuses = {d.domain: (d.status, d.summary) for d in report.domains}
        display_status, display_emoji = derive_display_status(investigation.risk_level, domain_statuses)

    return InvestigationResponse(
        investigation_id=investigation.id,
        status=investigation.status,
        structured_case=StructuredCase(**(investigation.structured_case or {})),
        report=report,
        display_status=display_status,
        display_emoji=display_emoji,
        messages=messages,
        evidence=evidence,
        created_at=investigation.created_at.isoformat() if investigation.created_at else None,
        updated_at=investigation.updated_at.isoformat() if investigation.updated_at else None,
    )


@router.post("/{investigation_id}/context", response_model=MessageResponse)
async def update_context(investigation_id: str, payload: ContextUpdateRequest, db: AsyncSession = Depends(get_db)):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")
    current = StructuredCase(**(investigation.structured_case or {}))
    data = current.model_dump()
    for key, value in payload.updates.items():
        if key in data:
            data[key] = value
    investigation.structured_case = StructuredCase(**data).model_dump()
    note = payload.note or "Updated investigation details."
    db.add(Message(investigation_id=investigation_id, role="user", content=note))
    try:
        assistant_message = await _save_report(investigation, db, note)
        db.add(Message(investigation_id=investigation_id, role="assistant", content=assistant_message))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Context verification failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Verification assistant is temporarily unavailable: {exc}") from exc
    return MessageResponse(
        assistant_message=assistant_message,
        structured_case=StructuredCase(**investigation.structured_case),
        ready_for_verification=True,
    )
