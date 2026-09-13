"""
Investigation chat endpoints - starting a case and continuing the conversation.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.session import get_db
from database.models import Investigation, Message, EvidenceItem
from schemas.case import (
    StructuredCase,
    InvestigationCreateRequest,
    InvestigationCreateResponse,
    MessageRequest,
    MessageResponse,
    MessageRecord,
    EvidenceItemSummary,
    InvestigationResponse,
    ContextUpdateRequest,
)
from risk.display_status import derive_display_status
from schemas.report import FinalReport
from agents.investigator import run_investigation_turn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investigations", tags=["investigation"])


@router.post("", response_model=InvestigationCreateResponse)
async def create_investigation(
    payload: InvestigationCreateRequest, db: AsyncSession = Depends(get_db)
):
    if not payload.initial_message or not payload.initial_message.strip():
        raise HTTPException(status_code=400, detail="initial_message must not be empty")

    investigation = Investigation(structured_case={})
    db.add(investigation)
    await db.flush()  # get the generated id before commit

    user_msg = Message(
        investigation_id=investigation.id, role="user", content=payload.initial_message
    )
    db.add(user_msg)

    try:
        assistant_message, updated_case, ready = await run_investigation_turn(
            conversation_history=[{"role": "user", "content": payload.initial_message}],
            current_case=StructuredCase(),
        )
    except Exception as exc:
        logger.error("Investigator turn failed while creating investigation: %s", exc, exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Investigation assistant is temporarily unavailable: {exc}") from exc

    assistant_msg = Message(
        investigation_id=investigation.id, role="assistant", content=assistant_message
    )
    db.add(assistant_msg)

    investigation.structured_case = updated_case.model_dump()
    investigation.status = "ready_for_verification" if ready else "in_progress"

    await db.commit()

    return InvestigationCreateResponse(
        investigation_id=investigation.id,
        assistant_message=assistant_message,
        structured_case=updated_case,
        ready_for_verification=ready,
    )


@router.post("/{investigation_id}/messages", response_model=MessageResponse)
async def continue_investigation(
    investigation_id: str, payload: MessageRequest, db: AsyncSession = Depends(get_db)
):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    if investigation.status not in ("in_progress", "ready_for_verification"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot continue chat on an investigation with status={investigation.status!r}.",
        )

    result = await db.execute(
        select(Message)
        .where(Message.investigation_id == investigation_id)
        .order_by(Message.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in result.scalars().all()]
    history.append({"role": "user", "content": payload.message})

    user_msg = Message(investigation_id=investigation_id, role="user", content=payload.message)
    db.add(user_msg)

    current_case = StructuredCase(**investigation.structured_case)
    try:
        assistant_message, updated_case, ready = await run_investigation_turn(
            conversation_history=history, current_case=current_case
        )
    except Exception as exc:
        logger.error(
            "Investigator turn failed for investigation_id=%s: %s",
            investigation_id, exc, exc_info=True,
        )
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Investigation assistant is temporarily unavailable: {exc}") from exc

    assistant_msg = Message(
        investigation_id=investigation_id, role="assistant", content=assistant_message
    )
    db.add(assistant_msg)

    investigation.structured_case = updated_case.model_dump()
    investigation.status = "ready_for_verification" if ready else "in_progress"

    await db.commit()

    return MessageResponse(
        assistant_message=assistant_message,
        structured_case=updated_case,
        ready_for_verification=ready,
    )


@router.get("/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(investigation_id: str, db: AsyncSession = Depends(get_db)):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    message_result = await db.execute(
        select(Message).where(Message.investigation_id == investigation_id).order_by(Message.created_at)
    )
    messages = [
        MessageRecord(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat(),
        )
        for m in message_result.scalars().all()
    ]

    evidence_result = await db.execute(
        select(EvidenceItem).where(EvidenceItem.investigation_id == investigation_id).order_by(EvidenceItem.created_at)
    )
    evidence = []
    for item in evidence_result.scalars().all():
        label = Path(item.file_path).name if item.file_path else "Pasted evidence"
        mime = None
        evidence_type = item.evidence_type
        if evidence_type == "document":
            mime = "application/pdf"
        evidence.append(
            EvidenceItemSummary(
                id=item.id,
                evidence_type=evidence_type,
                label=label,
                mime=mime,
                size_bytes=None,
                created_at=item.created_at.isoformat(),
            )
        )

    display_status, display_emoji = (None, None)
    report_data = investigation.final_report
    report = FinalReport(**report_data) if report_data else None
    if report is not None and investigation.risk_level:
        domain_statuses = {d.domain: (d.status, d.summary) for d in report.domains}
        display_status, display_emoji = derive_display_status(investigation.risk_level, domain_statuses)

    return InvestigationResponse(
        investigation_id=investigation.id,
        status=investigation.status,
        structured_case=StructuredCase(**investigation.structured_case),
        report=report.model_dump(mode="json") if report else None,
        display_status=display_status,
        display_emoji=display_emoji,
        messages=messages,
        evidence=evidence,
        created_at=investigation.created_at.isoformat(),
        updated_at=investigation.updated_at.isoformat(),
    )


@router.post("/{investigation_id}/context", response_model=MessageResponse)
async def update_context(
    investigation_id: str, payload: ContextUpdateRequest, db: AsyncSession = Depends(get_db)
):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if not payload.updates:
        raise HTTPException(status_code=400, detail="No updates supplied")

    allowed = {"country", "degree_level", "university", "program", "agent", "payment_amount_pkr", "funding_type", "scholarship"}
    current = StructuredCase(**investigation.structured_case).model_dump()
    payment_amount = payload.updates.get("payment_amount_pkr", current.get("payment_amount"))
    for key, value in payload.updates.items():
        if key not in allowed:
            continue
        if key == "payment_amount_pkr":
            current["payment_amount"] = value
        elif key in {"degree_level", "funding_type", "scholarship"}:
            current[key] = value
        else:
            current[key] = value

    if payment_amount is not None:
        current["payment_amount"] = payment_amount

    changed = ", ".join(f"{k}: {v}" for k, v in payload.updates.items())
    message_text = f"[Investigation profile updated] {changed}" + (f" — {payload.note}" if payload.note else "")
    db.add(Message(investigation_id=investigation_id, role="user", content=message_text))
    assistant_text = "I’ve updated the investigation profile. Continue the conversation or run verification again when you’re ready."
    db.add(Message(investigation_id=investigation_id, role="assistant", content=assistant_text))
    investigation.structured_case = current
    investigation.status = "ready_for_verification" if StructuredCase(**current).is_sufficient_for_verification() else "in_progress"
    await db.commit()
    return MessageResponse(
        assistant_message=assistant_text,
        structured_case=StructuredCase(**current),
        ready_for_verification=investigation.status == "ready_for_verification",
    )
