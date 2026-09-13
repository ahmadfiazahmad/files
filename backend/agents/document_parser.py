"""Evidence extraction with a simple Gemini -> Groq fallback."""
import io
from agents.llm_client import llm
from schemas.evidence import ExtractedDocumentClaims

EXTRACTION_PROMPT = """Extract only clearly visible/stated facts from study-abroad evidence for a Pakistani student.
It may be a WhatsApp screenshot, email, offer letter, invoice, scholarship notice or PDF.
Do not decide safe/scam. Use null when a field is unknown. Preserve useful claims.
"""

async def parse_file_evidence(file_bytes: bytes, mime_type: str) -> ExtractedDocumentClaims:
    if mime_type == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)[:12000]
            if text.strip():
                return await llm.generate_json(EXTRACTION_PROMPT, f"PDF text:\n{text}", ExtractedDocumentClaims)
        except Exception:
            pass
        # There is no dependable Groq PDF input path in the current SDK; when
        # text extraction is unavailable, return an explicit empty extraction
        # rather than failing the entire demo.
        return ExtractedDocumentClaims(source_type="pdf", claims=["PDF uploaded; text could not be extracted automatically."])
    return await llm.generate_multimodal_json(
        EXTRACTION_PROMPT,
        "Extract university, country, agent, program, payment amount/currency/method, dates, URLs and claims.",
        file_bytes,
        mime_type,
        ExtractedDocumentClaims,
    )

async def parse_image_evidence(image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractedDocumentClaims:
    return await parse_file_evidence(image_bytes, mime_type)

async def parse_text_evidence(text: str) -> ExtractedDocumentClaims:
    return await llm.generate_json(EXTRACTION_PROMPT, f"Evidence text:\n{text}", ExtractedDocumentClaims)
