"""
Master Pipeline Orchestrator v2

Runs Phases 1-7 end-to-end:
  P1: Ingestion & Normalization (UBNE)
  P2: Classification
  P2.5: Specification Extraction (NEW)
  P3: Sourcing + Candidate Generation
  P3.5: Real Pricing Engine (NEW)
  P3.6: Alternative Finder (NEW)
  P4: RL Decision Engine
  P4.5: BOM-Level Optimization (NEW)
  P5: 7-Section Report Generation
  P6/P7: Feedback & Learning

Backward compatible: old pipeline still works if new modules fail.
"""
import time
import logging
from typing import Dict, Any, List

from engine.ingestion.normalizer import process_bom
from engine.classification.classifier import classify_bom
from engine.sourcing.sourcing_engine import generate_candidate_strategies
from engine.decision.rl_engine import select_optimal_strategy
from engine.reporting.report_engine import generate_full_report
from engine.feedback.feedback_engine import ExecutionTracker, compute_feedback, update_memory
from engine.memory.memory_store import PricingMemory, SupplierMemory, DecisionMemory
from engine.integrations.currency_engine import get_exchange_rates
from core.schemas import PartCategory

logger = logging.getLogger(__name__)


class BOMIntelligenceEngine:
    def __init__(self):
        self.pm = PricingMemory()
        self.sm = SupplierMemory()
        self.dm = DecisionMemory()
        self.tracker = ExecutionTracker()

    def run_pipeline(
        self,
        file_path: str,
        user_location: str = "",
        target_currency: str = "USD",
        email: str = "",
    ) -> Dict[str, Any]:
        t0 = time.time()
        pt: Dict[str, float] = {}

        # ── Phase 1: Ingestion ──
        ts = time.time()
        try:
            from engine.ingestion.ubne import USE_NEW_NORMALIZER, ubne_process_bom
            if USE_NEW_NORMALIZER:
                items, ubne_diag = ubne_process_bom(file_path, user_location, target_currency, email)
            else:
                items = process_bom(file_path, user_location, target_currency, email)
                ubne_diag = None
        except Exception as e:
            logger.warning(f"UBNE failed ({e}), falling back to legacy")
            items = process_bom(file_path, user_location, target_currency, email)
            ubne_diag = None
        pt["p1_ingestion"] = round(time.time() - ts, 3)

        # ── Phase 2: Classification ──
        ts = time.time()
        classified = classify_bom(items)
        pt["p2_classification"] = round(time.time() - ts, 3)

        # ── Phase 2.5: Specification Extraction (NEW) ──
        ts = time.time()
        specs_data: Dict[str, Dict] = {}
        try:
            from engine.specs.spec_extractor import extract_specs
            for ci in classified:
                text = f"{ci.description} {ci.standard_text} {ci.material} {ci.notes}".strip()
                cat_hint = ci.category.value if ci.category else "auto"
                specs_data[ci.item_id] = extract_specs(text, category=cat_hint)
        except Exception as e:
            logger.warning(f"Spec extraction failed: {e}")
        pt["p2_5_specs"] = round(time.time() - ts, 3)

        # ── Phase 3: Sourcing / Candidate Generation ──
        ts = time.time()
        all_cands = generate_candidate_strategies(classified, user_location, self.sm, self.pm)
        pt["p3_sourcing"] = round(time.time() - ts, 3)

        # ── Phase 3.5: Real Pricing (NEW) ──
        ts = time.time()
        pricing_data: Dict[str, Dict] = {}
        try:
            from engine.pricing.pricing_engine import price_item
            for ci in classified:
                sp = specs_data.get(ci.item_id, {})
                cat_info = {
                    "geometry": ci.geometry.value if ci.geometry else "prismatic",
                    "tolerance": ci.tolerance.value if ci.tolerance else "standard",
                    "material_form": ci.material_form.value if ci.material_form else "billet",
                    "secondary_ops": ci.secondary_ops or [],
                }
                pricing_data[ci.item_id] = price_item(
                    specs=sp,
                    category=ci.category.value,
                    mpn=ci.mpn,
                    quantity=ci.quantity,
                    region="local",
                    category_info=cat_info,
                )
        except Exception as e:
            logger.warning(f"Pricing engine failed: {e}")
        pt["p3_5_pricing"] = round(time.time() - ts, 3)

        # ── Phase 3.6: Alternative Finder (NEW) ──
        ts = time.time()
        alternatives_data: Dict[str, List] = {}
        try:
            from engine.optimizer.alternative_engine import find_alternatives
            for ci in classified:
                sp = specs_data.get(ci.item_id, {})
                # Run alternatives for standard components AND anything with extractable specs
                if ci.category in (PartCategory.STANDARD, PartCategory.UNKNOWN) or sp.get("fastener_type") or sp.get("component_type"):
                    sp = specs_data.get(ci.item_id, {})
                    alternatives_data[ci.item_id] = find_alternatives(
                        sp, mpn=ci.mpn, quantity=ci.quantity,
                    )
        except Exception as e:
            logger.warning(f"Alternative finder failed: {e}")
        pt["p3_6_alternatives"] = round(time.time() - ts, 3)

        # ── Phase 4: RL Decision Engine ──
        ts = time.time()
        decisions = [
            select_optimal_strategy(ci, all_cands.get(ci.item_id, []), self.sm, self.dm)
            for ci in classified
        ]
        pt["p4_decision"] = round(time.time() - ts, 3)

        # ── Phase 4.5: BOM-Level Optimization (NEW) ──
        ts = time.time()
        optimization_data: Dict[str, Any] = {}
        try:
            from engine.optimizer.bom_optimizer import optimize_bom
            optimization_data = optimize_bom(classified, decisions, user_location)
        except Exception as e:
            logger.warning(f"BOM optimizer failed: {e}")
        pt["p4_5_optimization"] = round(time.time() - ts, 3)

        # ── Forex ──
        rates = get_exchange_rates(target_currency)

        # ── Phase 5: Report Generation (7 sections) ──
        ts = time.time()
        report = generate_full_report(
            classified, decisions, user_location, target_currency,
            self.sm, self.dm, self.pm, rates,
            specs_data=specs_data,
            pricing_data=pricing_data,
            optimization_data=optimization_data,
            alternatives_data=alternatives_data,
        )
        pt["p5_reporting"] = round(time.time() - ts, 3)

        # ── Persist memory ──
        self.sm.save()
        self.dm.save()
        self.pm.save()

        # ── Meta ──
        total_cands = sum(len(v) for v in all_cands.values())
        report["_meta"] = {
            "total_time_s": round(time.time() - t0, 3),
            "phase_times": pt,
            "items": len(items),
            "candidates": total_cands,
            "specs_extracted": len(specs_data),
            "priced": len(pricing_data),
            "alternatives_found": sum(len(v) for v in alternatives_data.values()),
            "version": "2.1.0",
        }

        if ubne_diag:
            report["_ubne_diagnostics"] = ubne_diag

        return report

    def submit_feedback(self, tracking_id, actual_cost=None, actual_days=None,
                        quality_ok=True, on_time=True):
        rec = self.tracker.get(tracking_id)
        if not rec:
            return {"error": "Not found"}
        if actual_cost is not None:
            rec["actual_cost"] = actual_cost
        if actual_days is not None:
            rec["actual_days"] = actual_days
        fb = compute_feedback(rec)
        fb.quality_ok = quality_ok
        fb.on_time = on_time
        update_memory(fb, self.sm, self.pm, self.dm, rec)
        return {
            "ok": True,
            "delta_cost": fb.delta_cost,
            "delta_time": fb.delta_time,
            "regret": fb.regret,
            "exploration_rate": self.dm.exploration_rate,
            "confidence": self.dm.confidence,
        }

    def memory_state(self):
        return {
            "pricing": {"n": len(self.pm.data.get("components", {}))},
            "suppliers": {
                "n": len(self.sm.data.get("suppliers", {})),
                "top": dict(list(self.sm.data.get("suppliers", {}).items())[:10]),
            },
            "decision": {
                "iterations": self.dm.iterations,
                "exploration_rate": self.dm.exploration_rate,
                "confidence": self.dm.confidence,
                "regret": self.dm.data.get("total_regret", 0),
            },
        }
