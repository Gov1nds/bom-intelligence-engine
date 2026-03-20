"""
PHASE 6+7 — Execution Tracking, Feedback, Memory Update.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from core.schemas import FeedbackRecord
from engine.memory.memory_store import SupplierMemory, PricingMemory, DecisionMemory
from config.settings import MemoryConfig

class ExecutionTracker:
    def __init__(self, fp=None):
        self.fp = fp or MemoryConfig.EXECUTION_TRACKING_FILE
        p = Path(self.fp)
        self.records = json.load(open(p)) if p.exists() else {}
    def save(self):
        Path(self.fp).parent.mkdir(parents=True, exist_ok=True)
        json.dump(self.records, open(self.fp,"w"), indent=2, default=str)
    def create(self, item_id, order_id, supplier_id, predicted_cost, predicted_days):
        tid = f"TRK-{item_id}-{order_id}"
        self.records[tid] = {"item_id":item_id,"order_id":order_id,"supplier_id":supplier_id,
                              "predicted_cost":predicted_cost,"predicted_days":predicted_days,
                              "milestones":{},"actual_cost":None,"actual_days":None,"completed":False}
        self.save(); return tid
    def milestone(self, tid, ms, cost=0, notes=""):
        if tid not in self.records: raise KeyError(tid)
        r = self.records[tid]
        r["milestones"][ms] = {"ts":datetime.utcnow().isoformat(),"cost":cost,"notes":notes}
        if ms == "T4":
            r["completed"] = True
            tc = sum(m.get("cost",0) for m in r["milestones"].values())
            if tc > 0: r["actual_cost"] = tc
            t0 = r["milestones"].get("T0",{}).get("ts")
            if t0:
                try: r["actual_days"] = (datetime.fromisoformat(r["milestones"]["T4"]["ts"]) - datetime.fromisoformat(t0)).days
                except: pass
        self.save()
    def get(self, tid): return self.records.get(tid)
    def completed(self): return [r for r in self.records.values() if r.get("completed")]

def compute_feedback(rec: Dict, best_cost=None) -> FeedbackRecord:
    pc = rec.get("predicted_cost", 0); ac = rec.get("actual_cost", pc)
    pd = rec.get("predicted_days", 0); ad = rec.get("actual_days", pd)
    if best_cost is None: best_cost = pc * 0.9
    return FeedbackRecord(item_id=rec.get("item_id",""), supplier_id=rec.get("supplier_id",""),
                          delta_cost=round(ac-pc,2), delta_time=round(ad-pd,1),
                          regret=round(max(0, ac-best_cost),2), on_time=ad<=pd)

def update_memory(fb: FeedbackRecord, sm: SupplierMemory, pm: PricingMemory, dm: DecisionMemory, rec: Dict):
    pc = rec.get("predicted_cost",0); pd = rec.get("predicted_days",0)
    sm.update_from_feedback(fb.supplier_id, pc+fb.delta_cost, pc, pd+int(fb.delta_time), pd, fb.quality_ok, fb.on_time)
    if pc+fb.delta_cost > 0: pm.update_price(fb.item_id, pc+fb.delta_cost, "feedback")
    if fb.regret > 0:
        region = fb.supplier_id.split("_")[0] if "_" in fb.supplier_id else "?"
        dm.add_regret(region, fb.regret)
    if pc > 0: dm.update_confidence(1.0 - abs(fb.delta_cost)/pc)
    dm.adapt_exploration()
    sm.save(); pm.save(); dm.save()
