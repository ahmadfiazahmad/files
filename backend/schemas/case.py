"""
Schemas for the structured case object and investigation chat.
"""
from pydantic import BaseModel, Field
from schemas.report import FinalReport


class StructuredCase(BaseModel):
    """
    The evolving structured representation of the student's situation.
    All fields optional since the investigation builds this up incrementally.
    """
    university: str | None = None
    country: str | None = None
    program: str | None = None
    agent: str | None = None
    payment_amount: float | None = None
    currency: str | None = None
    payment_purpose: str | None = None
    payment_method: str | None = None
    degree_level: str | None = None
    funding_type: str | None = None
    scholarship: str | None = None
    claims: list[str] = Field(default_factory=list)

    def missing_fields(self) -> list[str]:
        """Used by the investigator to decide what to ask next."""
        required = ["university", "country", "agent", "payment_amount", "payment_method"]
        return [f for f in required if getattr(self, f) in (None, "")]

    def is_sufficient_for_verification(self) -> bool:
        """Minimum bar to move from chat -> verification stage."""
        return self.university is not None and (
            self.agent is not None or self.payment_amount is not None
        )


class InvestigationCreateRequest(BaseModel):
    initial_message: str


class InvestigationCreateResponse(BaseModel):
    investigation_id: str
    assistant_message: str
    structured_case: StructuredCase
    ready_for_verification: bool


class MessageRequest(BaseModel):
    message: str


class MessageRecord(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class EvidenceItemSummary(BaseModel):
    id: str
    evidence_type: str
    label: str
    mime: str | None = None
    size_bytes: int | None = None
    created_at: str


class InvestigationResponse(BaseModel):
    investigation_id: str
    status: str
    structured_case: StructuredCase
    report: FinalReport | None = None
    display_status: str | None = None
    display_emoji: str | None = None
    messages: list[MessageRecord] = Field(default_factory=list)
    evidence: list[EvidenceItemSummary] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class ContextUpdateRequest(BaseModel):
    updates: dict[str, str | float | int | None] = Field(default_factory=dict)
    note: str | None = None


class MessageResponse(BaseModel):
    assistant_message: str
    structured_case: StructuredCase
    ready_for_verification: bool
