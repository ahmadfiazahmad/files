from pydantic import BaseModel, Field
from schemas.evidence import EvidenceRecord

class VerificationRunResponse(BaseModel):
    investigation_id: str
    status: str
    evidence_count: int
    risk_score: int
    risk_level: str
    # Draft mapping - see risk/display_status.py docstring for caveats.
    display_status: str
    display_emoji: str

class DomainSummary(BaseModel):
    domain: str
    status: str
    summary: str
    evidence: list[EvidenceRecord] = Field(default_factory=list)
