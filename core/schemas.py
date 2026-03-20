"""
Core data schemas for every phase of the pipeline.
"""
from __future__ import annotations
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import uuid

class PartCategory(str, Enum):
    STANDARD = "standard"
    RAW_MATERIAL = "raw_material"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

class ClassificationPath(str, Enum):
    PATH_3_1 = "3_1"
    PATH_3_2 = "3_2"
    PATH_3_3 = "3_3"

class ManufacturingProcess(str, Enum):
    CNC_3AXIS = "cnc_3axis"; CNC_5AXIS = "cnc_5axis"; CNC_TURNING = "cnc_turning"
    LASER_CUTTING = "laser_cutting"; WATERJET = "waterjet"; PLASMA = "plasma"
    PRESS_BRAKE = "press_brake"; STAMPING = "stamping"
    DIE_CASTING = "die_casting"; INJECTION_MOLDING = "injection_molding"
    SLS = "sls"; DMLS = "dmls"; SLA = "sla"
    EDM = "edm"; GRINDING = "grinding"; HONING = "honing"
    WELDING = "welding"; THREADING = "threading"
    SURFACE_COATING = "surface_coating"; HEAT_TREATMENT = "heat_treatment"
    FORGING = "forging"; CASTING = "casting"

class TransportMode(str, Enum):
    AIR = "air"; SEA = "sea"; ROAD = "road"; RAIL = "rail"

class DecisionMode(str, Enum):
    EXPLORATION = "exploration"; EXPLOITATION = "exploitation"; THOMPSON = "thompson_sampling"

class MaterialForm(str, Enum):
    SHEET = "sheet"; BILLET = "billet"; BAR = "bar"; TUBE = "tube"
    COMPOSITE = "composite"; POLYMER = "polymer"

class GeometryComplexity(str, Enum):
    FLAT_2D = "2d"; PRISMATIC = "2.5d"; FULL_3D = "3d"; MULTI_AXIS = "multi_axis"

class ToleranceClass(str, Enum):
    LOOSE = "loose"; STANDARD = "standard"; PRECISION = "precision"; ULTRA = "ultra"

# ---- Phase 1 output ----
@dataclass
class NormalizedBOMItem:
    item_id: str = ""
    raw_text: str = ""
    standard_text: str = ""
    quantity: int = 1
    description: str = ""
    part_number: str = ""
    mpn: str = ""
    manufacturer: str = ""
    make: str = ""
    material: str = ""
    notes: str = ""
    unit: str = "each"
    reference_ids: List[str] = field(default_factory=list)
    raw_row: Dict[str, Any] = field(default_factory=dict)

# ---- Phase 2 output ----
@dataclass
class ClassifiedItem(NormalizedBOMItem):
    category: PartCategory = PartCategory.UNKNOWN
    classification_path: ClassificationPath = ClassificationPath.PATH_3_1
    confidence: float = 0.0
    classification_reason: str = ""
    has_mpn: bool = False
    has_brand: bool = False
    is_generic: bool = False
    is_raw: bool = False
    is_custom: bool = False
    material_form: Optional[MaterialForm] = None
    geometry: Optional[GeometryComplexity] = None
    tolerance: Optional[ToleranceClass] = None
    secondary_ops: List[str] = field(default_factory=list)

# ---- Phase 3 structures ----
@dataclass
class TLCBreakdown:
    c_mfg: float = 0.0
    quantity: int = 1
    c_nre: float = 0.0
    c_log: float = 0.0
    tariff_rate: float = 0.0
    c_tariff: float = 0.0
    c_inventory: float = 0.0
    c_risk: float = 0.0
    c_compliance: float = 0.0
    base_tlc: float = 0.0
    industrial_tlc: float = 0.0
    def compute(self):
        self.c_tariff = self.c_mfg * self.quantity * self.tariff_rate
        self.base_tlc = (self.c_mfg * self.quantity) + self.c_nre + self.c_log + self.c_tariff
        self.industrial_tlc = self.base_tlc + self.c_inventory + self.c_risk + self.c_compliance
        return self.industrial_tlc
    def to_dict(self):
        return {k: round(getattr(self, k), 4) for k in self.__dataclass_fields__}

@dataclass
class SourcingCandidate:
    candidate_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    item_id: str = ""
    supplier_id: str = ""
    supplier_name: str = ""
    region: str = ""
    country: str = ""
    unit_price: float = 0.0
    moq: int = 1
    currency: str = "USD"
    quoted_lead_days: int = 0
    expected_lead_days: int = 0
    tlc: TLCBreakdown = field(default_factory=TLCBreakdown)
    simulated_tlc: float = 0.0
    risk_adjusted_tlc: float = 0.0
    uncertainty_score: float = 0.5
    process_chain: List[ManufacturingProcess] = field(default_factory=list)
    machining_time_hrs: float = 0.0
    labor_hours: float = 0.0
    setup_time_hrs: float = 0.0
    nre: float = 0.0
    from_memory: bool = False
    cost_buffer_pct: float = 0.10
    time_buffer_days: int = 3
    historical_variance: float = 0.5
    transport_mode: TransportMode = TransportMode.SEA
    quality_score: float = 0.5
    reliability_score: float = 0.5
    def to_dict(self):
        return {
            "candidate_id": self.candidate_id, "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name, "region": self.region,
            "unit_price": round(self.unit_price, 4), "moq": self.moq,
            "quoted_lead_days": self.quoted_lead_days, "expected_lead_days": self.expected_lead_days,
            "simulated_tlc": round(self.simulated_tlc, 2),
            "risk_adjusted_tlc": round(self.risk_adjusted_tlc, 2),
            "uncertainty_score": round(self.uncertainty_score, 3),
            "tlc_breakdown": self.tlc.to_dict(),
            "process_chain": [p.value for p in self.process_chain],
            "machining_time_hrs": round(self.machining_time_hrs, 2),
            "labor_hours": round(self.labor_hours, 2),
            "transport_mode": self.transport_mode.value,
        }

# ---- Phase 4 output ----
@dataclass
class DecisionExplanation:
    decision_mode: DecisionMode = DecisionMode.EXPLOITATION
    mode_probability: float = 0.0
    trigger_condition: str = ""
    selected_supplier_id: str = ""
    selected_region: str = ""
    selected_tlc: float = 0.0
    delta_vs_next_best: float = 0.0
    confidence_score: float = 0.0
    confidence_interval_pct: float = 0.0
    supply_risk: float = 0.0
    logistics_risk: float = 0.0
    cost_volatility: float = 0.0
    quality_risk: float = 0.0
    ucb_formula_used: str = ""
    tlc_proof: str = ""
    local_vs_offshore: str = ""
    volume_logic: str = ""
    contributes_to_exploration: bool = False
    expected_info_gain: float = 0.0
    def to_dict(self):
        return {
            "decision_mode": self.decision_mode.value,
            "trigger": self.trigger_condition,
            "selected_supplier_id": self.selected_supplier_id,
            "selected_region": self.selected_region,
            "selected_tlc": round(self.selected_tlc, 2),
            "delta_vs_next_best": round(self.delta_vs_next_best, 2),
            "confidence": round(self.confidence_score, 3),
            "confidence_interval_pct": round(self.confidence_interval_pct, 1),
            "risk": {"supply": round(self.supply_risk, 3), "logistics": round(self.logistics_risk, 3),
                     "cost_volatility": round(self.cost_volatility, 3), "quality": round(self.quality_risk, 3)},
            "math": {"ucb": self.ucb_formula_used, "tlc": self.tlc_proof},
            "strategy": {"local_vs_offshore": self.local_vs_offshore, "volume": self.volume_logic},
            "learning": {"exploration": self.contributes_to_exploration, "info_gain": round(self.expected_info_gain, 3)},
        }

@dataclass
class ItemDecision:
    item_id: str = ""
    description: str = ""
    quantity: int = 1
    category: PartCategory = PartCategory.UNKNOWN
    selected: Optional[SourcingCandidate] = None
    alternatives: List[SourcingCandidate] = field(default_factory=list)
    decision_mode: DecisionMode = DecisionMode.EXPLOITATION
    score: float = 0.0
    explanation: DecisionExplanation = field(default_factory=DecisionExplanation)
    all_candidates: List[SourcingCandidate] = field(default_factory=list)
    def to_dict(self):
        return {
            "item_id": self.item_id, "description": self.description,
            "quantity": self.quantity, "category": self.category.value,
            "selected_vendor": self.selected.to_dict() if self.selected else None,
            "alternatives": [a.to_dict() for a in self.alternatives[:3]],
            "decision_mode": self.decision_mode.value, "score": round(self.score, 4),
            "explanation": self.explanation.to_dict(),
        }

@dataclass
class FeedbackRecord:
    item_id: str = ""
    supplier_id: str = ""
    delta_cost: float = 0.0
    delta_time: float = 0.0
    regret: float = 0.0
    quality_ok: bool = True
    on_time: bool = True
