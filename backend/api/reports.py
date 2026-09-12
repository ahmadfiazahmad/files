"""
Results endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import Investigation
from schemas.report import ReportResponse, FinalReport
from risk.display_status import derive_display_status

router = APIRouter(prefix="/investigations", tags=["reports"])


@router.get("/{investigation_id}/results", response_model=ReportResponse)
async def get_results(investigation_id: str, db: AsyncSession = Depends(get_db)):
    investigation = await db.get(Investigation, investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")

    report = FinalReport(**investigation.final_report) if investigation.final_report else None

    display_status, display_emoji = (None, None)
    if report is not None and investigation.risk_level:
        domain_statuses = {d.domain: (d.status, d.summary) for d in report.domains}
        display_status, display_emoji = derive_display_status(investigation.risk_level, domain_statuses)

    return ReportResponse(
        investigation_id=investigation.id,
        status=investigation.status,
        structured_case=investigation.structured_case,
        report=report,
        display_status=display_status,
        display_emoji=display_emoji,
    )
