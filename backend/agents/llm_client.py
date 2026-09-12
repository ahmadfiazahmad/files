"""Unified AI client: Gemini primary, Groq fallback."""
import asyncio
import base64
import json
import logging
from typing import TypeVar, Type

from pydantic import BaseModel
from google import genai
from google.genai import types
from groq import AsyncGroq

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_gemini = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
_groq = AsyncGroq(api_key=settings.groq_api_key) if settings.groq_api_key else None

CHAT_MODEL = settings.gemini_model
VISION_MODEL = settings.gemini_model
EMBEDDING_MODEL = settings.gemini_embedding_model
GROQ_MODEL = settings.groq_model

TIMEOUT = settings.llm_call_timeout_seconds


class LLMClient:
    async def _gemini_call(self, contents, config=None):
        if not _gemini:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        return await asyncio.wait_for(
            asyncio.to_thread(
                _gemini.models.generate_content,
                model=CHAT_MODEL,
                contents=contents,
                config=config,
            ),
            timeout=TIMEOUT,
        )

    async def _groq_call(self, messages, json_mode=False):
        if not _groq:
            raise RuntimeError("GROQ_API_KEY is not configured")
        kwargs = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": 0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await asyncio.wait_for(
            _groq.chat.completions.create(**kwargs), timeout=TIMEOUT
        )
        return response.choices[0].message.content or ""

    async def generate_text(self, system: str, user: str) -> str:
        try:
            response = await self._gemini_call(
                f"SYSTEM:\n{system}\n\nUSER:\n{user}",
                types.GenerateContentConfig(max_output_tokens=4096),
            )
            return response.text or ""
        except Exception as exc:
            logger.warning(
                "Gemini generate_text failed (%s: %s); falling back to Groq.",
                type(exc).__name__, exc,
            )
            try:
                return await self._groq_call([
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ])
            except Exception as groq_exc:
                logger.error(
                    "Groq fallback for generate_text also failed: %s", groq_exc
                )
                raise RuntimeError(
                    "Both Gemini and Groq failed for generate_text"
                ) from groq_exc

    async def generate_json(self, system: str, user: str, schema: Type[T]) -> T:
        schema_json = schema.model_json_schema()
        try:
            response = await self._gemini_call(
                f"SYSTEM:\n{system}\n\nUSER:\n{user}",
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema_json,
                    max_output_tokens=4096,
                ),
            )
            return schema.model_validate_json(response.text)
        except Exception as exc:
            logger.warning(
                "Gemini generate_json (%s) failed (%s: %s); falling back to Groq.",
                schema.__name__, type(exc).__name__, exc,
            )
            try:
                raw = await self._groq_call(
                    [
                        {
                            "role": "system",
                            "content": system
                            + "\nReturn only JSON matching this schema:\n"
                            + json.dumps(schema_json),
                        },
                        {"role": "user", "content": user},
                    ],
                    json_mode=True,
                )
                return schema.model_validate_json(raw)
            except Exception as groq_exc:
                logger.error(
                    "Groq fallback for generate_json (%s) also failed: %s",
                    schema.__name__, groq_exc,
                )
                raise RuntimeError(
                    f"Both Gemini and Groq failed for generate_json({schema.__name__})"
                ) from groq_exc

    async def generate_multimodal_json(
        self, system: str, user: str, data: bytes, mime_type: str, schema: Type[T]
    ) -> T:
        schema_json = schema.model_json_schema()
        part = types.Part.from_bytes(data=data, mime_type=mime_type)
        try:
            response = await self._gemini_call(
                [part, f"SYSTEM:\n{system}\n\nTASK:\n{user}"],
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema_json,
                    max_output_tokens=4096,
                ),
            )
            return schema.model_validate_json(response.text)
        except Exception as exc:
            logger.warning(
                "Gemini generate_multimodal_json (%s) failed (%s: %s); "
                "attempting fallback.",
                schema.__name__, type(exc).__name__, exc,
            )
            if mime_type == "application/pdf":
                # Groq's OpenAI-compatible image_url input doesn't support
                # PDFs in this MVP, so there's no safe fallback path.
                logger.error(
                    "PDF extraction has no fallback path (Groq is image-only); "
                    "giving up on this evidence item."
                )
                raise RuntimeError(
                    "Gemini PDF extraction failed; PDF fallback is intentionally "
                    "disabled because Groq fallback is image-only in this MVP"
                ) from exc
            try:
                b64 = base64.b64encode(data).decode("utf-8")
                raw = await self._groq_call(
                    [
                        {
                            "role": "system",
                            "content": system
                            + "\nReturn only JSON matching this schema:\n"
                            + json.dumps(schema_json),
                        },
                        {"role": "user", "content": [
                            {"type": "text", "text": user},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                        ]},
                    ],
                    json_mode=True,
                )
                return schema.model_validate_json(raw)
            except Exception as groq_exc:
                logger.error(
                    "Groq image fallback for generate_multimodal_json (%s) also "
                    "failed: %s", schema.__name__, groq_exc,
                )
                raise RuntimeError(
                    f"Both Gemini and Groq failed for generate_multimodal_json({schema.__name__})"
                ) from groq_exc

    async def embed(self, text: str) -> list[float]:
        if not _gemini:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _gemini.models.embed_content,
                model=EMBEDDING_MODEL,
                contents=text,
            ),
            timeout=TIMEOUT,
        )
        return [float(v) for v in result.embeddings[0].values]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.gather(*(self.embed(t) for t in texts))

    async def google_search(self, prompt: str) -> dict:
        if not _gemini:
            return {"error": "GEMINI_API_KEY is not configured", "answer": None}
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    _gemini.models.generate_content,
                    model=CHAT_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        max_output_tokens=5000,
                    ),
                ),
                timeout=TIMEOUT,
            )
            grounding = None
            if response.candidates:
                metadata = getattr(response.candidates[0], "grounding_metadata", None)
                if metadata is not None and hasattr(metadata, "model_dump"):
                    grounding = metadata.model_dump(mode="json")
            return {"answer": response.text or "", "grounding": grounding}
        except Exception as exc:
            logger.warning(
                "Gemini google_search grounding call failed (%s: %s); this "
                "source will report unable_to_verify.", type(exc).__name__, exc,
            )
            return {"error": str(exc), "answer": None}


llm = LLMClient()
