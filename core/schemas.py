"""Core data schemas — ingestion + classification only."""
from __future__ import annotations
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


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


class MaterialForm(str, Enum):
    SHEET = "sheet"; BILLET = "billet"; BAR = "bar"; TUBE = "tube"
    COMPOSITE = "composite"; POLYMER = "polymer"


class GeometryComplexity(str, Enum):
    FLAT_2D = "2d"; PRISMATIC = "2.5d"; FULL_3D = "3d"; MULTI_AXIS = "multi_axis"


class ToleranceClass(str, Enum):
    LOOSE = "loose"; STANDARD = "standard"; PRECISION = "precision"; ULTRA = "ultra"


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