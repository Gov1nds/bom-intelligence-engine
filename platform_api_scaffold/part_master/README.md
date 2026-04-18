# Part Master Index — Platform-API Architecture

## Overview

The Part Master Index is a **platform-api responsibility** that stores, queries,
and learns from the BOM Intelligence Engine's normalization output. The analyser
remains 100% stateless — it emits `normalized_part_key` and `learning_signals`,
and the platform ingests and enriches them over time.

## Data Flow

```
┌─────────────────────┐     ┌──────────────────────────┐     ┌─────────────────────┐
│  BOM Intelligence   │     │     Platform API          │     │    Platform DB      │
│      Engine         │     │                          │     │                     │
│  (stateless)        │     │  ┌────────────────────┐  │     │  ┌───────────────┐  │
│                     │     │  │ Ingestion Service   │  │     │  │ part_master   │  │
│  raw_text ──────►   │     │  │                    │  │     │  │               │  │
│  normalize()        │────►│  │ ingest_learning_   │──┼────►│  │ records       │  │
│  ──────────►        │     │  │ signal()           │  │     │  │ aliases       │  │
│  NormalizationResp  │     │  │ upsert_part_       │  │     │  │ corrections   │  │
│  ├─ learning_signals│     │  │ record()           │  │     │  │ overrides     │  │
│  ├─ normalized_key  │     │  │ register_alias()   │  │     │  └───────┬───────┘  │
│  └─ canonical_name  │     │  └────────────────────┘  │     │          │          │
│                     │     │                          │     │          │          │
│                     │     │  ┌────────────────────┐  │     │          │          │
│                     │     │  │ Query Service       │  │     │          │          │
│                     │◄────│  │                    │◄─┼──────┤          │          │
│  part_master_index  │     │  │ lookup_by_key()    │  │     │          │          │
│  (optional startup  │     │  │ find_similar()     │  │     │          │          │
│   read-only dict)   │     │  │ get_coverage()     │  │     │          │          │
│                     │     │  └────────────────────┘  │     │          │          │
│                     │     │                          │     │          │          │
│                     │     │  ┌────────────────────┐  │     │          │          │
│                     │     │  │ Correction API      │  │     │          │          │
│                     │     │  │                    │──┼──────┤          │          │
│                     │     │  │ POST /correct-*    │  │     │          │          │
│                     │     │  │ POST /approve-*    │  │     │          │          │
│                     │     │  │ GET  /review-queue │  │     │          │          │
│                     │     │  └────────────────────┘  │     │          │          │
└─────────────────────┘     └──────────────────────────┘     └─────────────────────┘
```

## Correction Loop

1. **Analyser emits** `learning_signals` with `normalized_part_key`, `canonical_name`,
   `category`, `attributes`, `category_confidence`, `extraction_quality`
2. **Ingestion Service** upserts into Part Master — merges attributes, increments
   occurrence count, appends confidence history
3. **Fuzzy alias detection** (Jaro-Winkler > 0.92) flags potential aliases for review
4. **Human reviewers** use Correction API to fix category, attributes, canonical name
5. **Canonical overrides** are approved and stored as `CanonicalOverride` records
6. **Platform exports** approved Part Master data back to the analyser as an optional
   `part_master_index` dict at startup — the analyser treats this as a read-only
   in-memory reference, just like the JSON resource files

## Override Mechanism

When a `CanonicalOverride` is approved:
- The override's `approved_canonical_name` replaces the current canonical name
- The override's `approved_category` replaces the current category
- The override's `approved_attributes` merge into existing attributes
- The record's `review_status` changes to `"approved"`
- All changes are logged in the `correction_log` for audit trail

The override is non-destructive — the original analyser output is preserved in
`confidence_history` and `raw_input_samples`.

## Fuzzy Matching and Alias Proposals

When a new `normalized_part_key` arrives, the ingestion service computes
Jaro-Winkler similarity against all existing keys. If similarity > 0.92:
- The new record is flagged as `needs_review`
- It is NOT auto-merged — human review is required
- A similarity result is surfaced in the review queue

This prevents false merges while surfacing likely duplicates for consolidation.

## Future ML/Vector Search Upgrade Path

1. **Feature vectors** — The analyser already emits `ml_feature_vector` (when
   `EMIT_ML_FEATURES=True`). Platform can store these in the Part Master and
   use them for similarity search via numpy/sklearn.

2. **Embedding signals** — The analyser emits `embedding_signal` with
   `text_for_embedding` (deterministic canonical text). Platform can pass this
   to an embedding model (OpenAI, Anthropic, or open-source) and store the
   resulting vectors in a vector database (pgvector, Pinecone, Qdrant).

3. **Vector similarity search** — Replace Jaro-Winkler string comparison with
   cosine similarity on embedding vectors for semantic part matching.

4. **Classification model** — Train a classifier on the Part Master's
   `(raw_input, category)` pairs to improve classification confidence over time.

## Key Design Principles

- **Analyser stays stateless** — no DB calls, no HTTP calls during request processing
- **All corrections are logged** — non-destructive audit trail
- **Aliases are human-approved** — no auto-merging
- **Part Master is optional** — the analyser works perfectly without it
- **Platform owns all state** — the analyser owns all intelligence
