"""
RAG retriever - DEV implementation using in-memory numpy cosine similarity.

This module is intentionally the ONLY place that knows how similarity search
is performed. In production (Supabase + pgvector), only this file's internals
change to issue a SQL query instead of a numpy computation - callers
(verification/agent.py, etc.) never need to change.
"""
import numpy as np
from sqlalchemy import select
from database.session import AsyncSessionLocal
from database.models import FraudPattern
from rag.embeddings import embed_text

_cache: list[dict] | None = None  # {id, pattern, text, embedding: np.array}


async def _load_cache() -> list[dict]:
    global _cache
    if _cache is not None:
        return _cache

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FraudPattern))
        patterns = result.scalars().all()

    _cache = [
        {
            "id": p.id,
            "pattern": p.pattern,
            "category": p.category,
            "severity": p.severity,
            "text": p.text,
            "embedding": np.array(p.embedding) if p.embedding else None,
        }
        for p in patterns
        if p.embedding is not None
    ]
    return _cache


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


async def search_fraud_patterns(query: str, top_k: int = 3) -> list[dict]:
    """
    Returns top_k most similar fraud patterns to the query, each with a
    'similarity' score (0-1). Empty list if knowledge base isn't seeded yet.
    """
    cache = await _load_cache()
    if not cache:
        return []

    query_embedding = np.array(await embed_text(query))

    scored = [
        {**item, "similarity": _cosine_similarity(query_embedding, item["embedding"])}
        for item in cache
    ]
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


def invalidate_cache():
    """Call after re-ingesting the knowledge base."""
    global _cache
    _cache = None
