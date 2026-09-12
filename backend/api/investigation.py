"""
Investigation chat endpoints - starting a case and continuing the conversation.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.session import get_db
from database.models import Investigation, Message
from schemas.case import (
    StructuredCase,
    InvestigationCreateRequest,
    InvestigationCreateResponse,
    MessageRequest,
    MessageResponse,
)
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
