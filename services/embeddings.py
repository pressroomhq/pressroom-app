"""Embedding service — voyage-3-lite via Voyage AI API, cosine similarity utils.

Used by the SIGINT pipeline to:
  - Embed raw signals at ingest time (once per signal)
  - Embed org fingerprints (rebuilt when org settings change)
  - Score relevance: cosine(signal_embedding, org_fingerprint) → 0.0–1.0
  - Dedup: cosine > 0.92 between new signal and recent raw signals → skip

Model: voyage-3-lite (fast, cheap, 512-dim)
Auth: VOYAGE_API_KEY — get a free key at voyageai.com (50M tokens/mo free tier)
Storage: pgvector Vector(512) column — pass list[float] directly, no serialization needed
"""

import json
import math
import os
from typing import Optional

import httpx

VOYAGE_MODEL = "voyage-3-lite"
VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"

# Relevance threshold — signals below this score are filtered out for the org
RELEVANCE_THRESHOLD = 0.50

# Dedup threshold — signals above this similarity to a recent signal are skipped
DEDUP_THRESHOLD = 0.92


def _api_key() -> Optional[str]:
    # Try env first, then pydantic settings (which loads .env)
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        try:
            from config import settings
            key = settings.voyage_api_key
        except Exception:
            pass
    return key or None


async def embed(text: str) -> list[float]:
    """Embed a single text string. Returns float list or empty list on failure."""
    results = await embed_batch([text])
    return results[0] if results else []


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts in one API call. Returns list of float lists."""
    api_key = _api_key()
    if not api_key or not texts:
        return [[] for _ in texts]

    texts = [t[:8000].strip() for t in texts]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                VOYAGE_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": VOYAGE_MODEL,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = sorted(data["data"], key=lambda x: x["index"])
            return [r["embedding"] for r in results]
    except Exception:
        return [[] for _ in texts]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 if either is empty."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def serialize(embedding: list[float]) -> list[float]:
    """Return embedding as-is — pgvector column accepts list[float] directly."""
    return embedding


def deserialize(s) -> list[float]:
    """Normalize embedding from DB — pgvector returns numpy.ndarray.
    Handles list, tuple, ndarray, and legacy JSON strings.
    """
    if s is None:
        return []
    # numpy ndarray or list/tuple from pgvector
    try:
        import numpy as np
        if isinstance(s, np.ndarray):
            return s.tolist()
    except ImportError:
        pass
    if isinstance(s, (list, tuple)):
        return list(s)
    # legacy JSON string fallback
    try:
        return json.loads(s)
    except Exception:
        return []


def score_relevance(signal_embedding: list[float], org_embedding: list[float]) -> float:
    """Return relevance score 0.0–1.0. Above RELEVANCE_THRESHOLD = include."""
    return cosine(signal_embedding, org_embedding)


def is_duplicate(
    new_embedding: list[float],
    existing_embeddings: list[list[float]],
    threshold: float = DEDUP_THRESHOLD,
) -> bool:
    """Return True if new signal is too similar to any existing signal."""
    for existing in existing_embeddings:
        if cosine(new_embedding, existing) >= threshold:
            return True
    return False


def build_org_fingerprint_text(org_settings: dict) -> str:
    """Build the text string to embed as an org's relevance fingerprint.

    Combines company name, industry, topics, competitors, and audience
    into a dense context string. This is what signals are scored against.
    """
    parts = []

    name = org_settings.get("onboard_company_name") or org_settings.get("name", "")
    if name:
        parts.append(f"Company: {name}")

    industry = org_settings.get("onboard_industry", "")
    if industry:
        parts.append(f"Industry: {industry}")

    topics = org_settings.get("onboard_topics", "[]")
    if isinstance(topics, str):
        try:
            topics = json.loads(topics)
        except Exception:
            topics = []
    if topics:
        parts.append(f"Topics: {', '.join(topics)}")

    competitors = org_settings.get("onboard_competitors", "[]")
    if isinstance(competitors, str):
        try:
            competitors = json.loads(competitors)
        except Exception:
            competitors = []
    if competitors:
        parts.append(f"Competitors: {', '.join(competitors)}")

    audience = org_settings.get("onboard_audience", "")
    if audience:
        parts.append(f"Audience: {audience}")

    domain = org_settings.get("onboard_domain") or org_settings.get("domain", "")
    if domain:
        parts.append(f"Domain: {domain}")

    return ". ".join(parts)
