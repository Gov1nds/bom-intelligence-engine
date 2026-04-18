"""Embedding signal builder — text preparation for vector embeddings.

No embedding model is called here — this is text preparation only.
The output goes into learning_signals so platform can pass it to an
embedding model if desired.
"""
from __future__ import annotations

from typing import Any

_EMBEDDING_VERSION = "1.0.0"


def build_embedding_signal(
    canonical_name: str,
    category: str,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic embedding signal for vector search readiness.

    Args:
        canonical_name: The generated canonical name
        category: Part category
        attributes: Extracted attributes dictionary

    Returns:
        dict with text_for_embedding, structured_tags, and embedding_version
    """
    # Build deterministic text for embedding
    parts = [category, canonical_name]

    # Add key attributes as text
    for key in sorted(attributes.keys()):
        value = attributes[key]
        if value is not None and not isinstance(value, (list, dict)):
            parts.append(f"{key}:{value}")

    text_for_embedding = " ".join(str(p) for p in parts if p)

    # Build structured tags for sparse retrieval
    structured_tags = [f"category:{category}"]
    for key in sorted(attributes.keys()):
        value = attributes[key]
        if value is not None and not isinstance(value, (list, dict)):
            structured_tags.append(f"{key}:{value}")

    return {
        "text_for_embedding": text_for_embedding,
        "structured_tags": structured_tags,
        "embedding_version": _EMBEDDING_VERSION,
    }
