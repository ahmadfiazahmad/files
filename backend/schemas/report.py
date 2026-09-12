from pydantic import BaseModel, Field
from schemas.verification import DomainSummary


class ManualCheck(BaseModel):
    name: str
    url: str
    reason: str


class FinalReport(BaseModel):
    risk_level: str
    risk_score: int
    domains: list[DomainSummary]
    fraud_signals: list[str] = Field(default_factory=list)
    recommendation: str
    safer_action: str
    manual_checks: list[ManualCheck] = Field(default_factory=list)


class ReportResponse(BaseModel):
    investigation_id: str
    status: str
    structured_case: dict
    report: FinalReport | None = None
    # Best-effort student-facing status/emoji derived from risk_level and
    # domain coverage. See risk/display_status.py docstring: the mapping
    # between the app's internal enums and the 5-value 🟢🟡🟠🔴⚪ scheme was
    # ambiguous from the product spec, so this is a documented draft the
    # product owner should confirm before the frontend relies on it.
    display_status: str | None = None
    display_emoji: str | None = None
