import json
import logging

from pydantic import BaseModel
from agents.llm_client import llm
from schemas.evidence import EvidenceRecord

logger = logging.getLogger(__name__)


class NormalizedResult(BaseModel):
    result: str
    detail: str


PROMPT = """Normalize the raw source result into a conservative verification result.
Use exactly one result:
verified = source clearly confirms the claim
contradicted = source clearly conflicts with the claim
claimed = source only reports an entity's own claim
not_found = source was checked and found nothing relevant
unable_to_verify = source is unavailable, ambiguous, incomplete, or insufficient
Never infer fraud from absence alone. Never invent facts.
"""


async def normalize_source_result(domain, claim, source, source_type, authority, raw_data):
    raw = raw_data if isinstance(raw_data, str) else json.dumps(raw_data, default=str)
    try:
        result = await llm.generate_json(
            PROMPT,
            f"Claim: {claim}\nSource: {source} ({source_type})\nRaw result:\n{raw}",
            NormalizedResult,
        )
        return EvidenceRecord(
            domain=domain,
            claim=claim,
            source=source,
            source_type=source_type,
            authority=authority,
            result=result.result,
            detail=result.detail,
            raw_response=raw_data if isinstance(raw_data, dict) else {"raw_text": raw_data},
        )
    except Exception as exc:
        # A single normalization failure (LLM outage, malformed response that
        # doesn't validate against NormalizedResult/VerificationResult, etc.)
        # must NOT take down the whole verification pipeline. Degrade this
        # one source to unable_to_verify and keep going - the aggregator
        # already treats unable_to_verify conservatively.
        logger.error(
            "Normalization failed for source=%s domain=%s claim=%r: %s. "
            "Degrading this source to unable_to_verify.",
            source, domain, claim, exc,
        )
        return EvidenceRecord(
            domain=domain,
            claim=claim,
            source=source,
            source_type=source_type,
            authority=authority,
            result="unable_to_verify",
            detail=f"Normalization failed for this source ({type(exc).__name__}); "
                   f"treat as not independently confirmed.",
            raw_response=raw_data if isinstance(raw_data, dict) else {"raw_text": raw_data},
        )
