"""BOM Intelligence Engine — Orchestrator pipeline."""
import time
import hashlib
import logging
from typing import Any

from engine.ingestion.normalizer import ingest_file
from engine.classification.classifier import classify_bom
from engine.specs.spec_extractor import extract_specs
from engine.estimation.cost_estimator import estimate_cost
from engine.estimation.lead_time_risk import estimate_lead_time, estimate_risk
from core.schemas import PartCategory

logger = logging.getLogger("orchestrator")


def _canonical_key(ci) -> str:
    domain = ci.category.value if ci.category else "unknown"
    if ci.has_mpn and ci.mpn and len(ci.mpn.strip()) >= 4:
        clean = ci.mpn.strip().upper().replace(" ", "").replace("-", "")
        mfr = ci.manufacturer.strip().lower()[:20] if ci.manufacturer else ""
        return f"{domain}:mpn:{mfr}:{clean}".lower() if mfr else f"{domain}:mpn:{clean}".lower()
    desc = ci.description.strip().lower()[:40] if ci.description else ""
    mat = ci.material.strip().lower()[:20] if ci.material else ""
    return f"{domain}:{mat}:{desc}".replace(" ", "_")


class BOMIntelligenceEngine:

    def run_pipeline(self, file_path: str, user_location: str = "", target_currency: str = "USD", email: str = "") -> dict[str, Any]:
        t0 = time.time()
        pt = {}

        # File checksum
        try:
            with open(file_path, "rb") as f:
                file_checksum = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            file_checksum = None

        # Phase 1: Ingestion
        ts = time.time()
        raw_rows = ingest_file(file_path)
        pt["p1_ingestion"] = round(time.time() - ts, 3)

        # Phase 2: Classification
        ts = time.time()
        classified = classify_bom(raw_rows)
        pt["p2_classification"] = round(time.time() - ts, 3)

        # Phase 3: Spec extraction + cost/lead/risk estimation
        ts = time.time()
        components = []
        total_cost_low = 0
        total_cost_high = 0

        for ci in classified:
            text_blob = f"{ci.description} {ci.material} {ci.notes}".strip()
            specs = extract_specs(text_blob, ci.category.value)

            cost = estimate_cost(
                category=ci.category.value,
                material=ci.material,
                quantity=ci.quantity,
                is_custom=ci.is_custom,
                has_mpn=ci.has_mpn,
            )
            lead = estimate_lead_time(
                procurement_class=ci.procurement_class.value,
                category=ci.category.value,
                quantity=ci.quantity,
            )
            risk = estimate_risk(
                category=ci.category.value,
                procurement_class=ci.procurement_class.value,
                material=ci.material,
                quantity=ci.quantity,
                is_custom=ci.is_custom,
                has_mpn=ci.has_mpn,
                estimated_cost_mid=cost["unit_cost_mid"],
                estimated_lead_mid=lead["lead_time_mid_days"],
            )

            total_cost_low += cost["total_cost_low"]
            total_cost_high += cost["total_cost_high"]

            comp = {
                "item_id": ci.item_id,
                "raw_text": ci.raw_text,
                "standard_text": ci.standard_text,
                "description": ci.description,
                "quantity": ci.quantity,
                "part_number": ci.part_number,
                "mpn": ci.mpn,
                "manufacturer": ci.manufacturer,
                "supplier_name": ci.supplier_name,
                "material": ci.material,
                "notes": ci.notes,
                "unit": ci.unit,
                "category": ci.category.value,
                "classification_path": ci.classification_path,
                "classification_confidence": ci.confidence,
                "classification_reason": ci.classification_reason,
                "has_mpn": ci.has_mpn,
                "has_brand": ci.has_brand,
                "is_generic": ci.is_generic,
                "is_raw": ci.is_raw,
                "is_custom": ci.is_custom,
                "material_form": ci.material_form.value if ci.material_form else None,
                "geometry": ci.geometry,
                "tolerance": ci.tolerance,
                "secondary_ops": ci.secondary_ops,
                "procurement_class": ci.procurement_class.value,
                "rfq_required": ci.rfq_required,
                "drawing_required": ci.drawing_required,
                "canonical_part_key": _canonical_key(ci),
                "review_status": "auto" if ci.confidence >= 0.7 else "needs_review",
                "specs": specs,
                "cost_estimate": cost,
                "lead_time_estimate": lead,
                "risk_assessment": risk,
                "source_row": ci.source_row,
            }
            components.append(comp)

        pt["p3_specs_estimation"] = round(time.time() - ts, 3)

        # Category counts
        cat_counts = {}
        for cat in PartCategory:
            cnt = sum(1 for c in components if c["category"] == cat.value)
            if cnt > 0:
                cat_counts[cat.value] = cnt

        procurement_counts = {}
        for c in components:
            pc = c["procurement_class"]
            procurement_counts[pc] = procurement_counts.get(pc, 0) + 1

        rfq_required_count = sum(1 for c in components if c["rfq_required"])
        needs_review_count = sum(1 for c in components if c["review_status"] == "needs_review")

        return {
            "components": components,
            "summary": {
                "total_items": len(components),
                "categories": cat_counts,
                "procurement_classes": procurement_counts,
                "rfq_required_count": rfq_required_count,
                "needs_review_count": needs_review_count,
                "total_cost_range": {
                    "low": round(total_cost_low, 2),
                    "high": round(total_cost_high, 2),
                    "currency": target_currency,
                },
            },
            "_meta": {
                "total_time_s": round(time.time() - t0, 3),
                "phase_times": pt,
                "version": "4.0.0",
                "file_checksum": file_checksum,
            },
        }
