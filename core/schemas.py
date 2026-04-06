from enum import Enum


class PartCategory(str, Enum):
    fastener = "fastener"
    electrical = "electrical"
    electronics = "electronics"
    mechanical = "mechanical"
    raw_material = "raw_material"
    sheet_metal = "sheet_metal"
    machined = "machined"
    custom_mechanical = "custom_mechanical"
    pneumatic = "pneumatic"
    hydraulic = "hydraulic"
    optical = "optical"
    thermal = "thermal"
    cable_wiring = "cable_wiring"
    standard = "standard"
    unknown = "unknown"


class ProcurementClass(str, Enum):
    catalog_purchase = "catalog_purchase"
    custom_fabrication = "custom_fabrication"
    raw_material_order = "raw_material_order"
    subassembly = "subassembly"
    unknown = "unknown"


class MaterialForm(str, Enum):
    sheet = "sheet"
    bar = "bar"
    rod = "rod"
    tube = "tube"
    plate = "plate"
    wire = "wire"
    block = "block"
    casting = "casting"
    forging = "forging"
    powder = "powder"
    pellet = "pellet"
    other = "other"
