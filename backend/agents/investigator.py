import json

from pydantic import BaseModel
from agents.llm_client import llm
from schemas.case import StructuredCase

SYSTEM_PROMPT = """You are the investigation assistant for VerifyAbroad-AI, helping a Pakistani student investigate a possible study-abroad scam.
Understand English, Urdu, and Roman Urdu and reply in the same style.
Do not decide safe/scam during the chat. Gather facts only.
Ask ONE missing question at a time.
Prioritize: university, country, program, agent, payment amount/currency/purpose, payment method, notable claims.
Preserve known values unless the student corrects them.
Once university plus either agent or payment information is known, set ready_for_verification=true and ask for evidence if the student has it.
Never invent facts.
"""

class InvestigationTurn(BaseModel):
    assistant_message: str
    structured_case: StructuredCase
    ready_for_verification: bool

async def run_investigation_turn(conversation_history: list[dict], current_case: StructuredCase):
    # json.dumps (not the Python repr of the list) so the prompt uses
    # consistent, well-escaped quoting regardless of what languages/quote
    # characters appear in the student's English/Urdu/Roman Urdu messages.
    prompt = (
        f"Current structured case:\n{current_case.model_dump_json()}\n\n"
        f"Conversation history:\n{json.dumps(conversation_history, ensure_ascii=False)}\n\n"
        "Return the next assistant message and the updated case."
    )
    result = await llm.generate_json(SYSTEM_PROMPT, prompt, InvestigationTurn)
    ready = result.ready_for_verification or result.structured_case.is_sufficient_for_verification()
    return result.assistant_message, result.structured_case, ready
