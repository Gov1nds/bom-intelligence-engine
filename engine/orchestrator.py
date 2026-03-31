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
import asyncio
import copy
from threading import RLock
from typing import Dict, Any, List, Tuple

from engine.ingestion.normalizer import process_bom
from engine.classification.classifier import classify_bom
from core.schemas import PartCategory

logger = logging.getLogger(__name__)

# =========================
# 🔐 PIPELINE CACHE (NEW)
# =========================

_PIPELINE_CACHE: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
_CACHE_LOCK = RLock()
_CACHE_MAX = 128


def _cache_key(file_checksum: str, user_location: str, target_currency: str, email: str):
    return (file_checksum or "", user_location or "", target_currency or "", email or "")


def _cache_get(key):
    with _CACHE_LOCK:
        val = _PIPELINE_CACHE.get(key)
        return copy.deepcopy(val) if val else None


def _cache_set(key, value):
    with _CACHE_LOCK:
        if len(_PIPELINE_CACHE) >= _CACHE_MAX:
            _PIPELINE_CACHE.pop(next(iter(_PIPELINE_CACHE)))
        _PIPELINE_CACHE[key] = copy.deepcopy(value)


# =========================
# 🔑 CANONICAL KEY
# =========================

def _generate_canonical_key(ci) -> str:
    domain = ci.category.value if ci.category else "unknown"

    if ci.has_mpn and ci.mpn and len(ci.mpn.strip()) >= 4:
        clean_mpn = re.sub(r"[\s\-_]", "", ci.mpn.strip().upper())
        mfr = re.sub(r"[\s\-_]", "", ci.manufacturer.strip().lower())[:20] if ci.manufacturer else ""
        if mfr:
            return f"{domain}:mpn:{mfr}:{clean_mpn}".lower()
        return f"{domain}:mpn:{clean_mpn}".lower()

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
    if len(key) > 120:
        key = key[:80] + ":" + hashlib.sha256(key.encode()).hexdigest()[:12]
    return key


# =========================
# 🚀 ENGINE
# =========================

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

        # =========================
        # ⚡ CACHE CHECK (NEW)
        # =========================
        cache_key = _cache_key(file_checksum or "", user_location, target_currency, email)

        if file_checksum:
            cached = _cache_get(cache_key)
            if cached:
                cached.setdefault("_meta", {})["cache_hit"] = True
                cached["_meta"]["cache_key"] = ":".join(cache_key)
                return cached

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
                "supplier_name": ci.supplier_name if hasattr(ci, 'supplier_name') else "",
                "material": ci.material,
                "notes": ci.notes,
                "unit": ci.unit,

                # Classification
                "category": ci.category.value,
                "classification_path": ci.classification_path.value,
                "classification_confidence": ci.confidence,
                "classification_reason": ci.classification_reason,
                "classification_reason_code": getattr(ci, "classification_reason_code", ""),

                "has_mpn": ci.has_mpn,
                "has_brand": ci.has_brand,
                "is_generic": ci.is_generic,
                "is_raw": ci.is_raw,
                "is_custom": ci.is_custom,

                # Manufacturing
                "material_form": ci.material_form.value if ci.material_form else None,
                "geometry": ci.geometry.value if ci.geometry else None,
                "tolerance": ci.tolerance.value if ci.tolerance else None,
                "secondary_ops": ci.secondary_ops or [],

                # Procurement
                "procurement_class": ci.procurement_class.value if ci.procurement_class else "catalog_purchase",
                "rfq_required": ci.rfq_required,
                "drawing_required": ci.drawing_required,

                # Identity
                "canonical_part_key": _generate_canonical_key(ci),

                # Review
                "review_status": "auto" if ci.confidence >= 0.7 else "needs_review",
                "matched_master_id": None,

                # Specs
                "specs": specs_data.get(ci.item_id, {}),

                # 🔥 NEW: Failure metadata propagation
                "parse_status": getattr(ci, "parse_status", "ok"),
                "parse_reason_code": getattr(ci, "parse_reason_code", ""),
                "parse_reason": getattr(ci, "parse_reason", ""),
                "failure_metadata": getattr(ci, "failure_metadata", {}),

                # Dedup tracking
                "source_sheet": getattr(ci, "source_sheet", ""),
                "source_row": getattr(ci, "source_row", 0),
                "dedup_key": ci.raw_row.get("dedup_key", "") if getattr(ci, "raw_row", None) else "",
                "duplicate_count": ci.raw_row.get("duplicate_count", 1) if getattr(ci, "raw_row", None) else 1,
                "source_rows": ci.raw_row.get("source_rows", []) if getattr(ci, "raw_row", None) else [],
                "source_sheets": ci.raw_row.get("source_sheets", []) if getattr(ci, "raw_row", None) else [],
            }

            components.append(comp)

        # ── Summary ──
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
                "cache_hit": False,
                "cache_key": ":".join(cache_key),
                "normalizer_version": "ubne_1.4" if ubne_diag else "legacy_1.0",
            },
        }

        if ubne_diag:
            result["_ubne_diagnostics"] = ubne_diag

        # =========================
        # 💾 CACHE STORE (NEW)
        # =========================
        if file_checksum:
            _cache_set(cache_key, result)

        return result

    # =========================
    # ⚡ ASYNC WRAPPER (NEW)
    # =========================
    async def run_pipeline_async(
        self,
        file_path: str,
        user_location: str = "",
        target_currency: str = "USD",
        email: str = "",
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self.run_pipeline,
            file_path,
            user_location,
            target_currency,
            email,
        )