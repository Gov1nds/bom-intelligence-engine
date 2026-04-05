# PGI Hub — BOM Intelligence Engine

Pure-function microservice for BOM parsing, normalization, classification, and spec extraction.

## Responsibilities (ONLY)
- Parse CSV/Excel BOM files
- Normalize part descriptions
- Classify parts (standard, custom, raw material, etc.)
- Extract specifications
- Return structured JSON

## NOT responsible for
- Pricing, strategy, vendor matching, reporting, memory — all handled by Platform API

## Quick Start

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

## API

- `POST /api/analyze-bom` — Upload BOM file, returns v3 JSON
- `GET /health` — Health check

## Testing

```bash
pytest tests/ -v
```

## v3 Output Contract

```json
{
  "components": [...],
  "summary": { "total_items": N, "categories": {...} },
  "_meta": { "version": "4.1.0", "total_time_s": ..., "phase_times": {...} }
}
```
