"""Part_Master matching per GAP-035, WF-NORM-001 step 3."""
from __future__ import annotations
from dataclasses import dataclass, field
from engine.normalization.tokenizer import Token


@dataclass
class CandidateMatch:
    part_master_id: str | None = None
    canonical_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""
    attribute_match_summary: dict = field(default_factory=dict)
    is_selected: bool = False

    def to_dict(self) -> dict:
        return {
            "part_master_id": self.part_master_id,
            "canonical_name": self.canonical_name,
            "similarity_score": self.similarity_score,
            "match_method": self.match_method,
            "attribute_match_summary": self.attribute_match_summary,
            "is_selected": self.is_selected,
        }


def match_against_part_master(
    tokens: list[Token],
    expanded_text: str,
    category: str,
    mpn: str | None = None,
    manufacturer: str | None = None,
    part_master_index: object | None = None,
) -> list[CandidateMatch]:
    """Match against Part_Master. Gracefully degrades without index."""
    candidates: list[CandidateMatch] = []

    # 1. Exact MPN lookup
    if mpn and part_master_index and hasattr(part_master_index, "lookup_mpn"):
        exact = part_master_index.lookup_mpn(mpn, manufacturer)
        if exact:
            candidates.append(CandidateMatch(
                part_master_id=exact.id,
                canonical_name=getattr(exact, "canonical_name", mpn),
                similarity_score=1.0,
                match_method="exact_mpn",
                attribute_match_summary=getattr(exact, "attributes", {}),
                is_selected=True,
            ))
            return candidates

    # 2. Semantic embedding (if model available)
    if part_master_index and hasattr(part_master_index, "semantic_search"):
        semantic_results = part_master_index.semantic_search(expanded_text, top_n=5)
        for r in semantic_results:
            candidates.append(CandidateMatch(
                part_master_id=getattr(r, "id", None),
                canonical_name=getattr(r, "canonical_name", ""),
                similarity_score=getattr(r, "score", 0.0),
                match_method="semantic_embedding",
                attribute_match_summary=getattr(r, "attributes", {}),
            ))

    # 3. Taxonomy map fallback
    if not candidates:
        candidates.append(CandidateMatch(
            part_master_id=None,
            canonical_name=expanded_text[:80],
            similarity_score=0.3,
            match_method="taxonomy_map",
            attribute_match_summary={"category": category},
        ))

    # Select best
    candidates.sort(key=lambda c: c.similarity_score, reverse=True)
    candidates[0].is_selected = True
    return candidates
