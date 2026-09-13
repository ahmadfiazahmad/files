"""Small, reliable intake assistant for the hackathon MVP.

The assistant does not run a complicated planner. Each user message is first
structured into the case object (Gemini -> Groq fallback), the new facts are
merged into the existing case, and then one missing question is asked. After
five user turns we stop asking questions and move on to verification.
"""
import json
import re
from pydantic import BaseModel, Field
from agents.llm_client import llm
from schemas.case import StructuredCase

MAX_QUESTIONS = 5

SYSTEM_PROMPT = """You are the intake assistant for VerifyAbroad-AI, a study-abroad scam verification tool for Pakistani students.
Read English, Urdu and Roman Urdu. Extract only facts clearly stated by the student.
Do not invent facts. Do not change an already-known field unless the student clearly corrects it.
Return JSON only. When a value is unknown, use null.
"""

class CaseExtraction(BaseModel):
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


def _merge_case(current: StructuredCase, extracted: CaseExtraction) -> StructuredCase:
    data = current.model_dump()
    for key, value in extracted.model_dump().items():
        if key == "claims":
            data["claims"] = list(dict.fromkeys([*(data.get("claims") or []), *(value or [])]))[:20]
        elif value not in (None, ""):
            data[key] = value
    return StructuredCase(**data)


def _heuristic_extract(text: str) -> CaseExtraction:
    lower = text.lower()
    country_map = {
        "uk": "United Kingdom", "u.k.": "United Kingdom", "england": "United Kingdom",
        "germany": "Germany", "canada": "Canada", "australia": "Australia",
        "usa": "United States", "us": "United States", "america": "United States",
        "turkey": "Turkey", "uae": "United Arab Emirates", "ireland": "Ireland",
    }
    country = next((v for k, v in country_map.items() if k in lower), None)
    degree = None
    for token, value in [("mbbs", "MBBS"), ("ms ", "MS"), ("master", "MS"), ("msc", "MS"), ("bachelor", "BS"), ("phd", "PhD")]:
        if token in lower:
            degree = value
            break
    amount = None
    currency = None
    m = re.search(r"(?:(pkr|rs\.?|rupees?)\s*)?(\d+(?:\.\d+)?)\s*(lakh|lac|k|thousand|million)?", lower)
    if m:
        try:
            amount = float(m.group(2))
            unit = (m.group(3) or "").lower()
            if unit in {"lakh", "lac"}: amount *= 100000
            elif unit == "k": amount *= 1000
            elif unit == "thousand": amount *= 1000
            elif unit == "million": amount *= 1000000
            currency = "PKR" if "pkr" in lower or "rs" in lower or "rupee" in lower else None
        except ValueError:
            pass
    agent = None
    ma = re.search(r"(?:agent|consultant|consultancy)\s*(?:is|:|named|name)?\s*([A-Z][\w& .'-]{2,60})", text, re.I)
    if ma:
        agent = ma.group(1).strip(" .:-")
    university = None
    mu = re.search(r"([A-Z][A-Za-z0-9& .'-]{2,80}(?:University|Universit[y|ies]|College|Institute))", text)
    if mu:
        university = mu.group(1).strip()
    method = None
    for candidate in ["jazzcash", "easypaisa", "bank transfer", "bank account", "cash", "crypto", "usdt"]:
        if candidate in lower:
            method = candidate.title()
            break
    return CaseExtraction(
        university=university, country=country, agent=agent, payment_amount=amount,
        currency=currency, payment_method=method, degree_level=degree,
        claims=[text.strip()[:500]] if text.strip() else [],
    )


async def extract_case(text: str, current_case: StructuredCase) -> StructuredCase:
    prompt = (
        f"Current case: {current_case.model_dump_json()}\n\n"
        f"Student message:\n{text}\n\n"
        "Extract newly stated facts and return the CaseExtraction schema."
    )
    try:
        extracted = await llm.generate_json(SYSTEM_PROMPT, prompt, CaseExtraction)
    except Exception:
        extracted = _heuristic_extract(text)
    return _merge_case(current_case, extracted)


def missing_question(case: StructuredCase) -> str | None:
    if not case.university:
        return "Which university is this offer or request about?"
    if not case.country:
        return "Which country is the university in?"
    if not case.agent:
        return "What is the agent or consultant's name?"
    if case.payment_amount is None:
        return "How much money are they asking you to pay, and in which currency?"
    if not case.payment_method:
        return "How are they asking you to pay (bank transfer, JazzCash, Easypaisa, card, etc.)?"
    return None


async def run_investigation_turn(conversation_history: list[dict], current_case: StructuredCase):
    last_user = next((m.get("content", "") for m in reversed(conversation_history) if m.get("role") == "user"), "")
    updated_case = await extract_case(last_user, current_case)
    user_turns = sum(1 for m in conversation_history if m.get("role") == "user")
    ready = updated_case.is_sufficient_for_verification() or user_turns >= MAX_QUESTIONS

    if ready:
        if updated_case.is_sufficient_for_verification():
            message = (
                "Thanks — I have enough information to start the verification. "
                "I’ll check the university, consultant/payment claims and any evidence you provided."
            )
        else:
            message = (
                "I’ve reached the information limit for this chat, so I’ll proceed with a best-effort verification "
                "using the details available and clearly flag anything that could not be confirmed."
            )
    else:
        question = missing_question(updated_case) or "Please share any other detail from the offer or message."
        message = question
    return message, updated_case, ready
