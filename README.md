# BOM Intelligence Engine v2.0.0

Self-learning BOM analysis system with reinforcement learning, multi-region sourcing, industrial TLC computation, and feedback-driven improvement.

## Quick Start

```bash
pip install -r requirements.txt
python main.py --sample                    # Run with 15-item sample BOM
python main.py my_bom.csv --currency EUR   # Analyze your BOM
python main.py --sample -o report.json     # Save JSON report
python main.py --memory                    # Inspect learning state
python main.py --serve                     # Start FastAPI server on :8000
```

## Architecture

```
BOM File → Phase 1 (Parse+NLP) → Phase 2 (Classify) → Phase 3 (Source+TLC)
         → Phase 4 (RL Decision) → Phase 5 (Report) → JSON Output
                                                     ↓
         Phase 6 (Track Execution) → Phase 7 (Feedback) → Memory Update ↻
```

### Phase 1 — Ingestion & Normalization
Parses CSV/XLSX. Expands abbreviations (Res→resistor, Cap→capacitor, SS→stainless_steel). Scales values (10k→10000). Extracts MPN, manufacturer, quantity.

### Phase 2 — Classification (Strict)
1. MPN or known brand → **STANDARD** (3_1)
2. Custom fabrication keywords → **CUSTOM** (3_3)
3. Raw material keywords → **RAW** (3_2)
4. Generic component keyword → **STANDARD** (3_1)
5. Fallback

### Phase 3 — Sourcing + Simulation
- 11 configurable regions (US, CN, IN, VN, EU, JP, KR, TW, TH, MX, local)
- Learning-aware cost/time buffers from Supplier_Memory
- Industrial TLC: `(C_mfg×Q) + C_nre + C_log + Tariff + Inventory + Risk + Compliance`
- Custom part process selection (CNC 3/5-axis, laser, stamping, injection molding, etc.)

### Phase 4 — RL Decision Engine
- UCB (Upper Confidence Bound) with risk penalty
- Thompson Sampling for sparse data
- Directed exploration (high uncertainty × low TLC)
- Deterministic fallback if RL picks outlier (>3× median)
- Adaptive exploration rate

### Phase 5 — Reporting
6-section structured JSON: Executive Summary, Component Breakdown, Sourcing Strategy, Financial, Recommendation, Learning Snapshot.

### Phase 6+7 — Execution Tracking & Feedback
Track milestones T0→T4. Compute delta_cost, delta_time, regret. Update Supplier_Memory, Pricing_Memory, Decision_Memory.

## API Endpoints (--serve)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze-bom` | Upload BOM file, get full analysis |
| GET | `/api/memory` | Inspect memory state |
| GET | `/health` | Health check |

## Configuration

All regions, RL parameters, API keys, and memory paths are in `config/settings.py`. Regions are configurable via `RegionConfig.REGIONS` — no hardcoded region logic.

## Memory Files

Stored in `data/memory/`. Persist across runs. Delete to reset learning.
- `supplier_memory.json` — cost buffers, time buffers, variance, defect rates
- `decision_memory.json` — iterations, exploration rate, confidence, regret
- `pricing_memory.json` — component/commodity price baselines
