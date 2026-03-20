"""
Master Pipeline Orchestrator — runs Phases 1-5 end-to-end.
Also provides Phase 6+7 tracking/feedback APIs.
"""
import time, logging
from typing import Dict, Any, List
from engine.ingestion.normalizer import process_bom
from engine.classification.classifier import classify_bom
from engine.sourcing.sourcing_engine import generate_candidate_strategies
from engine.decision.rl_engine import select_optimal_strategy
from engine.reporting.report_engine import generate_full_report
from engine.feedback.feedback_engine import ExecutionTracker, compute_feedback, update_memory
from engine.memory.memory_store import PricingMemory, SupplierMemory, DecisionMemory
from engine.integrations.currency_engine import get_exchange_rates

logger = logging.getLogger(__name__)

class BOMIntelligenceEngine:
    def __init__(self):
        self.pm = PricingMemory()
        self.sm = SupplierMemory()
        self.dm = DecisionMemory()
        self.tracker = ExecutionTracker()

    def run_pipeline(self, file_path: str, user_location: str = "", target_currency: str = "USD", email: str = "") -> Dict[str, Any]:
        t0 = time.time(); pt = {}
        # Phase 1
        ts = time.time()
        items = process_bom(file_path, user_location, target_currency, email)
        pt["p1_ingestion"] = round(time.time()-ts, 3)
        # Phase 2
        ts = time.time()
        classified = classify_bom(items)
        pt["p2_classification"] = round(time.time()-ts, 3)
        # Phase 3
        ts = time.time()
        all_cands = generate_candidate_strategies(classified, user_location, self.sm, self.pm)
        pt["p3_sourcing"] = round(time.time()-ts, 3)
        # Phase 4
        ts = time.time()
        decisions = [select_optimal_strategy(ci, all_cands.get(ci.item_id, []), self.sm, self.dm) for ci in classified]
        pt["p4_decision"] = round(time.time()-ts, 3)
        # Forex
        rates = get_exchange_rates(target_currency)
        # Phase 5
        ts = time.time()
        report = generate_full_report(classified, decisions, user_location, target_currency, self.sm, self.dm, self.pm, rates)
        pt["p5_reporting"] = round(time.time()-ts, 3)
        # Persist
        self.sm.save(); self.dm.save(); self.pm.save()
        total_cands = sum(len(v) for v in all_cands.values())
        report["_meta"] = {"total_time_s":round(time.time()-t0,3),"phase_times":pt,
                           "items":len(items),"candidates":total_cands,"version":"2.0.0"}
        return report

    def submit_feedback(self, tracking_id, actual_cost=None, actual_days=None, quality_ok=True, on_time=True):
        rec = self.tracker.get(tracking_id)
        if not rec: return {"error": "Not found"}
        if actual_cost is not None: rec["actual_cost"] = actual_cost
        if actual_days is not None: rec["actual_days"] = actual_days
        fb = compute_feedback(rec); fb.quality_ok = quality_ok; fb.on_time = on_time
        update_memory(fb, self.sm, self.pm, self.dm, rec)
        return {"ok":True,"delta_cost":fb.delta_cost,"delta_time":fb.delta_time,
                "regret":fb.regret,"exploration_rate":self.dm.exploration_rate,"confidence":self.dm.confidence}

    def memory_state(self):
        return {"pricing":{"n":len(self.pm.data.get("components",{}))},
                "suppliers":{"n":len(self.sm.data.get("suppliers",{})),
                             "top":dict(list(self.sm.data.get("suppliers",{}).items())[:10])},
                "decision":{"iterations":self.dm.iterations,"exploration_rate":self.dm.exploration_rate,
                            "confidence":self.dm.confidence,"regret":self.dm.data.get("total_regret",0)}}
