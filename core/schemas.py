"""BOM Intelligence Engine — Core schemas and contracts (v5.0.0)."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field

SCHEMA_VERSION = "5.0.0"

# ── Enums ──

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
    connector = "connector"
    sensor = "sensor"
    semiconductor = "semiconductor"
    passive_component = "passive_component"
    power_supply = "power_supply"
    enclosure = "enclosure"
    adhesive_sealant = "adhesive_sealant"

class ProcurementClass(str, Enum):
    catalog_purchase = "catalog_purchase"
    custom_fabrication = "custom_fabrication"
    raw_material_order = "raw_material_order"
    subassembly = "subassembly"
    unknown = "unknown"

class MaterialForm(str, Enum):
    sheet = "sheet"; bar = "bar"; rod = "rod"; tube = "tube"
    plate = "plate"; wire = "wire"; block = "block"; casting = "casting"
    forging = "forging"; powder = "powder"; pellet = "pellet"; other = "other"

class RiskFlagType(str, Enum):
    SOLE_SOURCE = "SOLE_SOURCE"; LONG_LEAD = "LONG_LEAD"
    HIGH_TARIFF = "HIGH_TARIFF"; CURRENCY_VOLATILE = "CURRENCY_VOLATILE"
    GEOPOLITICAL_RISK = "GEOPOLITICAL_RISK"; COMPLIANCE_GAP = "COMPLIANCE_GAP"
    EXOTIC_MATERIAL = "EXOTIC_MATERIAL"; NO_MPN = "NO_MPN"
    CUSTOM_PART = "CUSTOM_PART"; HIGH_VALUE = "HIGH_VALUE"

class FreshnessStatus(str, Enum):
    FRESH = "FRESH"; STALE = "STALE"; EXPIRED = "EXPIRED"; ESTIMATED = "ESTIMATED"

class WeightProfile(str, Enum):
    speed_first = "speed_first"; cost_first = "cost_first"
    quality_first = "quality_first"; balanced = "balanced"

class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"; MEDIUM = "MEDIUM"; LOW = "LOW"

# ── Shared Types ──

class Money(BaseModel):
    amount: str = Field(..., description="DECIMAL(20,8) string")
    currency: str = Field(..., min_length=3, max_length=3)

class Address(BaseModel):
    line1: str = ""; line2: Optional[str] = None; city: str = ""
    state_region: Optional[str] = None; postal_code: Optional[str] = None
    country_code: str = ""; lat: Optional[float] = None; lng: Optional[float] = None

class TtlWindow(BaseModel):
    data_type: str = ""; fetched_at: Optional[datetime] = None
    ttl_seconds: int = 0; freshness_status: FreshnessStatus = FreshnessStatus.ESTIMATED
    source: str = ""

class RiskFlag(BaseModel):
    flag_type: RiskFlagType; severity: str = "low"
    mitigation: str = ""; data_source: str = ""

class AmbiguityFlag(BaseModel):
    flag_type: str; reason: str; impact_on_confidence: float = 0.0

class EngineEventSchema(BaseModel):
    event_id: str; event_type: str; bom_line_id: str
    correlation_id: str; idempotency_key: str; timestamp: str
    payload: dict = Field(default_factory=dict)

# ── Normalization ──

class ProjectContext(BaseModel):
    target_country: str = ""; stage_type: str = ""
    delivery_location: Optional[Address] = None

class NormalizationRequest(BaseModel):
    bom_line_id: UUID
    raw_text: str = Field(..., min_length=1)
    project_context: ProjectContext = Field(default_factory=ProjectContext)
    idempotency_key: str = ""

class CandidateMatchOutput(BaseModel):
    part_master_id: Optional[str] = None; canonical_name: str = ""
    similarity_score: float = 0.0; match_method: str = ""
    attribute_match_summary: dict = Field(default_factory=dict)
    is_selected: bool = False

class NormalizationTraceOutput(BaseModel):
    tokens_extracted: list[dict] = Field(default_factory=list)
    unit_conversion_applied: list[dict] = Field(default_factory=list)
    abbreviations_expanded: list[dict] = Field(default_factory=list)
    candidate_matches: list[dict] = Field(default_factory=list)
    selected_match_confidence: Optional[float] = None
    ambiguity_flags: list[AmbiguityFlag] = Field(default_factory=list)
    review_required: bool = False; review_reason: Optional[str] = None
    split_detected: bool = False; processing_time_ms: float = 0.0

class NormalizedItem(BaseModel):
    part_name: str = ""; category: str = "unknown"
    subcategory: Optional[str] = None; spec_json: dict = Field(default_factory=dict)
    quantity: int = 1; unit: str = "each"
    manufacturer_part_number: Optional[str] = None
    canonical_name: str = ""
    normalized_part_key: str = ""
    canonical_key: str = ""
    suggested_processes: list[str] = Field(default_factory=list)
    requires_rfq: bool = False
    drawing_required: bool = False
    review_flags: list[str] = Field(default_factory=list)
    uncertainty_flags: list[str] = Field(default_factory=list)

class NormalizationResponse(BaseModel):
    bom_line_id: UUID; normalized: NormalizedItem
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    ambiguity_flags: list[str] = Field(default_factory=list)
    split_detected: bool = False
    split_candidates: Optional[list[dict]] = None
    merge_candidate_ids: Optional[list[UUID]] = None
    matched_part_master_id: Optional[str] = None
    normalization_trace: NormalizationTraceOutput = Field(default_factory=NormalizationTraceOutput)
    model_version: str = SCHEMA_VERSION
    events: list[EngineEventSchema] = Field(default_factory=list)

# ── Enrichment ──

class EnrichmentProjectContext(ProjectContext):
    preferred_currency: str = "USD"; incoterm_preference: Optional[str] = None

class NormalizedData(BaseModel):
    part_name: str = ""; category: str = "unknown"
    spec_json: dict = Field(default_factory=dict); quantity: int = 1; unit: str = "each"
    canonical_key: str = ""; manufacturer_part_number: Optional[str] = None
    material: str = ""; is_custom: bool = False; has_mpn: bool = False
    procurement_class: str = "unknown"
    market_data_cache: dict = Field(default_factory=dict)
    tariff_data_cache: dict = Field(default_factory=dict)
    logistics_data_cache: dict = Field(default_factory=dict)

class EnrichmentRequest(BaseModel):
    bom_line_id: UUID
    normalized_data: NormalizedData = Field(default_factory=NormalizedData)
    project_context: EnrichmentProjectContext = Field(default_factory=EnrichmentProjectContext)
    idempotency_key: str = ""

class PriceBand(BaseModel):
    floor: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))
    mid: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))
    ceiling: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))

class MarketEnrichment(BaseModel):
    price_band: PriceBand = Field(default_factory=PriceBand)
    sources: list[str] = Field(default_factory=list)
    data_freshness: Optional[TtlWindow] = None

class TariffEnrichment(BaseModel):
    hs_code: Optional[str] = None; duty_rate_pct: float = 0.0
    fta_eligible: bool = False; data_source: str = ""
    data_freshness: Optional[TtlWindow] = None

class LogisticsEnrichment(BaseModel):
    freight_estimate: Optional[Money] = None
    lead_time_band: Optional[dict] = None
    data_freshness: Optional[TtlWindow] = None

class EnrichmentResponse(BaseModel):
    bom_line_id: UUID
    market_enrichment: MarketEnrichment = Field(default_factory=MarketEnrichment)
    tariff_enrichment: TariffEnrichment = Field(default_factory=TariffEnrichment)
    logistics_enrichment: LogisticsEnrichment = Field(default_factory=LogisticsEnrichment)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    data_freshness_summary: list[TtlWindow] = Field(default_factory=list)
    events: list[EngineEventSchema] = Field(default_factory=list)

# ── Scoring ──

class VendorCandidate(BaseModel):
    vendor_id: str; vendor_name: str = ""
    unit_price: Optional[str] = None; tooling_cost: Optional[str] = None
    moq: int = 1; lead_time_days: Optional[int] = None
    on_time_rate: Optional[float] = None; quality_rating: Optional[float] = None
    certifications: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    country_code: str = ""; currency: str = "USD"
    payment_terms: Optional[str] = None; response_speed_hours: Optional[int] = None

class EnrichmentData(BaseModel):
    quantity: int = 1; category: str = "unknown"
    procurement_class: str = "unknown"; material: str = ""
    is_custom: bool = False; has_mpn: bool = False
    market_enrichment: Optional[MarketEnrichment] = None
    tariff_enrichment: Optional[TariffEnrichment] = None
    logistics_enrichment: Optional[LogisticsEnrichment] = None
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    data_freshness_summary: list[TtlWindow] = Field(default_factory=list)

class ScoringRequest(BaseModel):
    bom_line_id: UUID
    enrichment_data: EnrichmentData = Field(default_factory=EnrichmentData)
    candidate_vendors: list[VendorCandidate] = Field(default_factory=list)
    weight_profile: WeightProfile = WeightProfile.balanced
    project_context: ProjectContext = Field(default_factory=ProjectContext)
    idempotency_key: str = ""

class TLCBreakdown(BaseModel):
    manufacturing: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))
    nre: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))
    logistics: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))
    tariff: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))
    forex_adjustment: Money = Field(default_factory=lambda: Money(amount="0", currency="USD"))

class VendorScoreEntry(BaseModel):
    vendor_id: str; composite_score: float = 0.0
    dimension_scores: dict = Field(default_factory=dict)
    tlc: Optional[Money] = None; tlc_breakdown: Optional[TLCBreakdown] = None
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    eliminated: bool = False; elimination_reason: Optional[str] = None
    explanation: str = ""

class ScoringResponse(BaseModel):
    bom_line_id: UUID
    vendor_scores: list[VendorScoreEntry] = Field(default_factory=list)
    weight_profile_applied: dict = Field(default_factory=dict)
    data_sources_snapshot: dict = Field(default_factory=dict)
    events: list[EngineEventSchema] = Field(default_factory=list)

# ── Strategy ──

class ScoringData(BaseModel):
    vendor_scores: list[VendorScoreEntry] = Field(default_factory=list)
    weight_profile_applied: dict = Field(default_factory=dict)

class StrategyRequest(BaseModel):
    bom_line_id: UUID
    score_data: ScoringData = Field(default_factory=ScoringData)
    enrichment_data: EnrichmentData = Field(default_factory=EnrichmentData)
    project_context: ProjectContext = Field(default_factory=ProjectContext)
    idempotency_key: str = ""

class StrategyRecommendation(BaseModel):
    sourcing_mode: str = "single_source"
    recommended_vendor_ids: list[str] = Field(default_factory=list)
    tlc_comparison: dict = Field(default_factory=dict)
    crossover_quantity: Optional[int] = None; explanation: str = ""

class StrategyResponse(BaseModel):
    bom_line_id: UUID
    strategy_recommendation: StrategyRecommendation = Field(default_factory=StrategyRecommendation)
    substitution_candidates: list[dict] = Field(default_factory=list)
    consolidation_signals: Optional[dict] = None
    data_freshness_summary: list[TtlWindow] = Field(default_factory=list)
    source_evidence: list[dict] = Field(default_factory=list)
    events: list[EngineEventSchema] = Field(default_factory=list)

# ── Error ──

class FieldError(BaseModel):
    field: str; message: str

class ErrorEnvelope(BaseModel):
    error_code: str; message: str; trace_id: str = ""
    details: Optional[list[FieldError]] = None