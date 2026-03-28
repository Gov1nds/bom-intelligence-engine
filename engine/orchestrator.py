"""
BOM Intelligence Engine — Pure Function Orchestrator

ONLY does:
  P1: Ingestion & Normalization (UBNE)
  P2: Classification (expanded taxonomy)
  P2.5: Specification Extraction

Returns structured JSON. No pricing. No decisions. No memory. No reports.
"""
import time
import hashlib
import re
import logging
from typing import Dict, Any, List

from engine.ingestion.normalizer import process_bom
from engine.classification.classifier import classify_bom
from core.schemas import PartCategory

logger = logging.getLogger(__name__)


def _generate_canonical_key(ci) -> str:
    """
    Generate a stable, deterministic canonical part key from normalized attributes.
    Format: {domain}:{form_or_type}:{key_specs}
    Keys are lowercase, no spaces, reproducible.
    """
    domain = ci.category.value if ci.category else "unknown"

    # For MPN-based parts, use mpn as key
    if ci.has_mpn and ci.mpn and len(ci.mpn.strip()) >= 4:
        clean_mpn = re.sub(r"[\s\-_]", "", ci.mpn.strip().upper())
        mfr = re.sub(r"[\s\-_]", "", ci.manufacturer.strip().lower())[:20] if ci.manufacturer else ""
        if mfr:
            return f"{domain}:mpn:{mfr}:{clean_mpn}".lower()
        return f"{domain}:mpn:{clean_mpn}".lower()

    # For material/form based parts
    form = ci.material_form.value if ci.material_form else ""
    material = re.sub(r"[\s_]+", "_", ci.material.strip().lower())[:30] if ci.material else ""
    desc = re.sub(r"[\s_]+", "_", ci.standard_text.strip().lower())[:40] if ci.standard_text else ""

    parts = [domain]
    if form:
        parts.append(form)
    if material:
        parts.append(material)
    if desc:
        parts.append(desc)

    key = ":".join(parts)
    # Ensure deterministic: hash long keys
    if len(key) > 120:
        key = key[:80] + ":" + hashlib.sha256(key.encode()).hexdigest()[:12]
    return key


class BOMIntelligenceEngine:
    """Stateless BOM parser + classifier. No memory, no side effects."""

    def run_pipeline(
        self,
        file_path: str,
        user_location: str = "",
        target_currency: str = "USD",
        email: str = "",
    ) -> Dict[str, Any]:
        t0 = time.time()
        pt: Dict[str, float] = {}

        # ── File checksum ──
        try:
            with open(file_path, "rb") as f:
                file_checksum = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            file_checksum = None

        # ── Phase 1: Ingestion ──
        ts = time.time()
        try:
            from engine.ingestion.ubne import USE_NEW_NORMALIZER, ubne_process_bom
            if USE_NEW_NORMALIZER:
                items, ubne_diag = ubne_process_bom(
                    file_path, user_location, target_currency, email
                )
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

        # ── Phase 2.5: Specification Extraction ──
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

        # ── Build output ──
        components = []
        for ci in classified:
            comp = {
                "item_id": ci.item_id,
                "raw_text": ci.raw_text,
                "standard_text": ci.standard_text,
                "description": ci.description,
                "quantity": ci.quantity,
                "part_number": ci.part_number,
                "mpn": ci.mpn,
                "manufacturer": ci.manufacturer,
                "material": ci.material,
                "notes": ci.notes,
                "unit": ci.unit,
                # Classification
                "category": ci.category.value,
                "classification_path": ci.classification_path.value,
                "classification_confidence": ci.confidence,
                "classification_reason": ci.classification_reason,
                "has_mpn": ci.has_mpn,
                "has_brand": ci.has_brand,
                "is_generic": ci.is_generic,
                "is_raw": ci.is_raw,
                "is_custom": ci.is_custom,
                # Manufacturing attributes
                "material_form": ci.material_form.value if ci.material_form else None,
                "geometry": ci.geometry.value if ci.geometry else None,
                "tolerance": ci.tolerance.value if ci.tolerance else None,
                "secondary_ops": ci.secondary_ops or [],
                # Procurement intent (NEW)
                "procurement_class": ci.procurement_class.value if ci.procurement_class else "catalog_purchase",
                "rfq_required": ci.rfq_required,
                "drawing_required": ci.drawing_required,
                # Canonical identity
                "canonical_part_key": _generate_canonical_key(ci),
                # Specs
                "specs": specs_data.get(ci.item_id, {}),
            }
            components.append(comp)

        # Expanded category summary
        all_cats = set(PartCategory)
        cat_counts = {}
        for cat in all_cats:
            cat_counts[cat.value] = sum(1 for c in components if c["category"] == cat.value)

        result = {
            "components": components,
            "summary": {
                "total_items": len(components),
                "categories": cat_counts,
            },
            "_meta": {
                "total_time_s": round(time.time() - t0, 3),
                "phase_times": pt,
                "version": "4.1.0",
                "file_checksum": file_checksum,
                "normalizer_version": "ubne_1.4" if ubne_diag else "legacy_1.0",
            },
        }

        if ubne_diag:
            result["_ubne_diagnostics"] = ubne_diag

        return result