"""Pydantic schemas for evidence extraction and normalized verification."""
from enum import Enum
from pydantic import BaseModel, Field


class AuthorityLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class VerificationResult(str, Enum):
    verified = "verified"
    not_found = "not_found"
    claimed = "claimed"
    contradicted = "contradicted"
    unable_to_verify = "unable_to_verify"


class Domain(str, Enum):
    institution = "institution"
    agent = "agent"
    payment = "payment"
    document = "document"


class EvidenceRecord(BaseModel):
    """Common shape consumed by the aggregator/risk engine."""
    domain: Domain
    claim: str
    source: str
    source_type: str
    authority: AuthorityLevel
    result: VerificationResult
    detail: str | None = None
    raw_response: dict | None = None


class EvidenceUploadResponse(BaseModel):
    evidence_id: str
    evidence_type: str
    extracted_data: dict


class ExtractedDocumentClaims(BaseModel):
    """Structured facts extracted from screenshots, PDFs, emails, chats, etc."""
    source_type: str | None = None
    university: str | None = None
    agent_name: str | None = None
    program: str | None = None
    student_name: str | None = None
    application_id: str | None = None
    claims: list[str] = Field(default_factory=list)
    payment_amount: float | None = None
    currency: str | None = None
    payment_deadline: str | None = None
    payment_method: str | None = None
    payment_url: str | None = None
    intake: str | None = None
    issue_date: str | None = None
