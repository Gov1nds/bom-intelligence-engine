"""
Memory System — JSON-persisted learning stores.
PricingMemory, SupplierMemory, DecisionMemory.
"""
import json, math, os, tempfile
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
from config.settings import MemoryConfig, RLConfig

def _atomic_save(filepath: str, data: dict):
    """Write JSON atomically: write to temp, then rename."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(Path(filepath).parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, filepath)  # atomic on same filesystem
    except:
        try: os.unlink(tmp)
        except: pass
        raise

def _safe_load(filepath: str, default: dict) -> dict:
    p = Path(filepath)
    if p.exists():
        try:
            with open(p, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return default
    return default

class PricingMemory:
    def __init__(self, fp=None):
        self.fp = fp or MemoryConfig.PRICING_MEMORY_FILE
        self.data = self._load()
    def _load(self):
        return _safe_load(self.fp, {"components": {}, "commodities": {}})
    def save(self):
        _atomic_save(self.fp, self.data)
    def get_baseline(self, key: str) -> Optional[float]:
        e = self.data["components"].get(key)
        return e.get("baseline") if e else None
    def update_price(self, key: str, price: float, source=""):
        lr = MemoryConfig.PRICING_LEARNING_RATE
        e = self.data["components"].get(key, {})
        old = e.get("baseline", price)
        self.data["components"][key] = {
            "baseline": round(old * (1-lr) + price * lr, 6),
            "last": round(price, 6), "n": e.get("n", 0) + 1,
        }
    def get_commodity(self, name: str) -> Optional[float]:
        e = self.data["commodities"].get(name.lower())
        return e.get("price") if e else None
    def update_commodity(self, name: str, price: float):
        self.data["commodities"][name.lower()] = {"price": price, "ts": datetime.utcnow().isoformat()}

class SupplierMemory:
    def __init__(self, fp=None):
        self.fp = fp or MemoryConfig.SUPPLIER_MEMORY_FILE
        self.data = self._load()
    def _load(self):
        return _safe_load(self.fp, {"suppliers": {}})
    def save(self):
        _atomic_save(self.fp, self.data)
    def get(self, sid: str) -> Optional[Dict]:
        return self.data["suppliers"].get(sid)
    def exists(self, sid: str) -> bool:
        return sid in self.data["suppliers"]
    def _ensure(self, sid: str) -> Dict:
        if sid not in self.data["suppliers"]:
            self.data["suppliers"][sid] = {
                "cost_buffer_pct": MemoryConfig.COST_BUFFER_DEFAULT,
                "time_buffer_days": MemoryConfig.TIME_BUFFER_DEFAULT_DAYS,
                "variance": 0.5, "orders": 0, "selections": 0,
                "defect_rate": 0.0, "on_time_rate": 1.0, "avg_tlc": 0.0,
            }
        return self.data["suppliers"][sid]
    def cost_buffer(self, sid: str) -> float:
        s = self.get(sid)
        return s["cost_buffer_pct"] if s else MemoryConfig.COST_BUFFER_DEFAULT
    def time_buffer(self, sid: str) -> int:
        s = self.get(sid)
        return s["time_buffer_days"] if s else MemoryConfig.TIME_BUFFER_DEFAULT_DAYS
    def variance(self, sid: str) -> float:
        s = self.get(sid)
        return s["variance"] if s else 0.8
    def selections(self, sid: str) -> int:
        s = self.get(sid)
        return s.get("selections", 0) if s else 0
    def record_selection(self, sid: str, tlc: float):
        s = self._ensure(sid)
        s["selections"] = s.get("selections", 0) + 1
        old = s.get("avg_tlc", tlc) or tlc
        s["avg_tlc"] = round(old * 0.9 + tlc * 0.1, 4)
    def update_from_feedback(self, sid, actual_cost, predicted_cost, actual_days, predicted_days, quality_ok, on_time):
        lr = MemoryConfig.SUPPLIER_LEARNING_RATE
        s = self._ensure(sid)
        if predicted_cost > 0:
            overrun = (actual_cost - predicted_cost) / predicted_cost
            s["cost_buffer_pct"] = round(s["cost_buffer_pct"] * (1-lr) + overrun * lr, 4)
            sq = ((actual_cost - predicted_cost) / predicted_cost) ** 2
            s["variance"] = round(s["variance"] * (1-lr) + sq * lr, 4)
        s["time_buffer_days"] = round(s["time_buffer_days"] * (1-lr) + (actual_days - predicted_days) * lr)
        n = s["orders"]
        s["defect_rate"] = round((s["defect_rate"] * n + (0 if quality_ok else 1)) / (n+1), 4)
        s["on_time_rate"] = round((s["on_time_rate"] * n + (1 if on_time else 0)) / (n+1), 4)
        s["orders"] = n + 1

class DecisionMemory:
    def __init__(self, fp=None):
        self.fp = fp or MemoryConfig.DECISION_MEMORY_FILE
        self.data = self._load()
    def _load(self):
        return _safe_load(self.fp, {
            "iterations": 0, "exploration_rate": RLConfig.GLOBAL_EXPLORATION_RATE,
            "confidence": 0.5, "total_regret": 0.0, "region_regret": {},
        })
    def save(self):
        _atomic_save(self.fp, self.data)
    @property
    def iterations(self): return self.data.get("iterations", 0)
    @property
    def exploration_rate(self): return self.data.get("exploration_rate", RLConfig.GLOBAL_EXPLORATION_RATE)
    @property
    def confidence(self): return self.data.get("confidence", 0.5)
    def record(self, item_id, supplier_id, mode, tlc, region):
        self.data["iterations"] = self.data.get("iterations", 0) + 1
    def region_regret(self, region: str) -> float:
        return self.data.get("region_regret", {}).get(region, 0.0)
    def add_regret(self, region: str, regret: float):
        self.data["total_regret"] = self.data.get("total_regret", 0) + regret
        rr = self.data.setdefault("region_regret", {})
        rr[region] = rr.get(region, 0) + regret
    def update_confidence(self, accuracy: float):
        old = self.data.get("confidence", 0.5)
        self.data["confidence"] = round(old * 0.9 + max(0, min(1, accuracy)) * 0.1, 4)
    def adapt_exploration(self):
        conf = self.data.get("confidence", 0.5)
        n = max(self.data.get("iterations", 1), 1)
        avg_regret = self.data.get("total_regret", 0) / n
        delta = RLConfig.REGRET_GROWTH_RATE if avg_regret > 0.1 else (-RLConfig.CONFIDENCE_DECAY_RATE if conf > 0.7 else 0)
        r = self.data.get("exploration_rate", RLConfig.GLOBAL_EXPLORATION_RATE) + delta
        self.data["exploration_rate"] = round(max(RLConfig.MIN_EXPLORATION_RATE, min(RLConfig.MAX_EXPLORATION_RATE, r)), 4)
