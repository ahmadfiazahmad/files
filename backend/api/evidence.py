import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from database.session import get_db
from database.models import Investigation, EvidenceItem
from schemas.evidence import EvidenceUploadResponse
from agents.document_parser import parse_file_evidence, parse_text_evidence
from storage.base import save_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investigations", tags=["evidence"])

@router.post("/{investigation_id}/evidence", response_model=EvidenceUploadResponse)
async def upload_evidence(
    investigation_id: str,
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    text = text.strip() if text else text
    if not file and not text:
        raise HTTPException(status_code=400, detail="Provide either file or text evidence")
    if file and text:
        raise HTTPException(status_code=400, detail="Provide either file or text, not both")

    if file:
        mime = file.content_type or "application/octet-stream"
        if not (mime.startswith("image/") or mime == "application/pdf"):
            raise HTTPException(status_code=400, detail="Supported files: images and PDF documents")
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if len(contents) > 15 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large for the MVP (15 MB max)")
        try:
            path = await save_file(investigation_id, file.filename or "evidence", contents)
            extracted = await parse_file_evidence(contents, mime)
        except Exception as exc:
            logger.error(
                "Evidence file extraction failed for investigation_id=%s: %s",
                investigation_id, exc, exc_info=True,
            )
            raise HTTPException(status_code=502, detail=f"Evidence extraction failed: {exc}") from exc
        evidence_type = "document" if mime == "application/pdf" else "image"
        raw_text = None
    else:
        path = None
        try:
            extracted = await parse_text_evidence(text)
        except Exception as exc:
            logger.error(
                "Evidence text extraction failed for investigation_id=%s: %s",
                investigation_id, exc, exc_info=True,
            )
            raise HTTPException(status_code=502, detail=f"Evidence extraction failed: {exc}") from exc
        evidence_type = "text"
        raw_text = text

    item = EvidenceItem(
        investigation_id=investigation_id,
        evidence_type=evidence_type,
        file_path=path,
        raw_text=raw_text,
        extracted_data=extracted.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return EvidenceUploadResponse(
        evidence_id=item.id,
        evidence_type=evidence_type,
        extracted_data=extracted.model_dump(),
    )
