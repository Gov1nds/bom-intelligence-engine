"""
PHASE C — Pricing Engine

Provides real-world pricing for all component types:
  - Standard: Octopart API (with fallback to parametric estimation)
  - Raw material: LME/commodity baseline + regional multiplier
  - Custom/machined: material + machining time + complexity (NO final price)

All prices are market-realistic. No fictional hash-based pricing.
"""

import re
import math
import hashlib
import logging
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger("pricing_engine")

# ══════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════

OCTOPART_API_KEY = os.getenv("OCTOPART_API_KEY", "")

# Realistic base prices by component type (USD, for estimation when API unavailable)
_COMPONENT_BASE_PRICES = {
    "resistor": {"base": 0.003, "per_power_w": 0.02, "precision_mult": 2.0},
    "capacitor": {"base": 0.01, "per_uf": 0.002, "voltage_mult": 0.001},
    "inductor": {"base": 0.05, "per_uh": 0.001},
    "diode": {"base": 0.02},
    "transistor": {"base": 0.05},
    "mosfet": {"base": 0.15},
    "led": {"base": 0.02},
    "connector": {"base": 0.20},
    "relay": {"base": 1.50},
    "fuse": {"base": 0.10},
    "crystal": {"base": 0.30},
    "ic": {"base": 1.00},
    "microcontroller": {"base": 3.00},
    "regulator": {"base": 0.50},
    "sensor": {"base": 2.00},
    "switch": {"base": 0.30},
    "transformer": {"base": 5.00},
}

# LME / commodity base prices (USD per kg, approximate current market)
_COMMODITY_PRICES = {
    "stainless_steel": 3.50,
    "carbon_steel": 0.80,
    "alloy_steel": 1.20,
    "mild_steel": 0.75,
    "aluminum": 2.60,
    "copper": 8.50,
    "brass": 5.50,
    "bronze": 7.00,
    "titanium": 25.00,
    "plastic": 2.00,
    "nylon": 3.50,
    "abs": 2.20,
    "peek": 80.00,
    "ptfe": 15.00,
    "pom": 3.00,
}

# Regional cost multipliers
_REGION_MULT = {
    "IN": 0.35, "CN": 0.40, "VN": 0.42, "TH": 0.45,
    "MX": 0.55, "EU": 0.85, "US": 1.00, "JP": 1.10,
    "KR": 0.80, "TW": 0.70, "local": 1.00,
}

# Machine hourly rates by region (USD/hr)
_MACHINE_RATES = {
    "IN": 18, "CN": 22, "VN": 20, "TH": 22,
    "MX": 30, "EU": 65, "US": 75, "JP": 80,
    "KR": 50, "TW": 40, "local": 60,
}

# Fastener pricing (USD per piece, by type and material)
_FASTENER_PRICES = {
    "bolt": {"stainless_steel": 0.25, "carbon_steel": 0.08, "alloy_steel": 0.15, "default": 0.10},
    "screw": {"stainless_steel": 0.15, "carbon_steel": 0.05, "default": 0.06},
    "nut": {"stainless_steel": 0.08, "carbon_steel": 0.03, "default": 0.04},
    "washer": {"stainless_steel": 0.05, "carbon_steel": 0.02, "default": 0.02},
    "rivet": {"default": 0.05},
    "pin": {"default": 0.08},
    "spring": {"default": 0.30},
    "stud": {"stainless_steel": 0.30, "carbon_steel": 0.12, "default": 0.15},
}


# ══════════════════════════════════════════════════════════
# STANDARD COMPONENT PRICING
# ══════════════════════════════════════════════════════════

def price_standard_component(specs: Dict[str, Any], mpn: str = "", quantity: int = 1) -> Dict[str, Any]:
    """
    Price a standard electronic/mechanical component.
    Tries: 1) MPN API lookup  2) Spec-based parametric estimation  3) Type-based baseline
    """
    result = {
        "source": "estimated",
        "unit_price": 0.0,
        "currency": "USD",
        "stock": None,
        "lead_days": None,
        "supplier": None,
        "moq": 1,
        "confidence": "low",
        "alternatives": [],
    }

    # 1) Try MPN-based API lookup
    if mpn and len(mpn) >= 3:
        api_result = _query_octopart(mpn)
        if api_result:
            result.update(api_result)
            result["source"] = "api"
            result["confidence"] = "high"
            return result

    # 2) Fastener pricing (mechanical standard parts)
    ft = specs.get("fastener_type")
    if ft and ft in _FASTENER_PRICES:
        mat_fam = specs.get("material_family", "default")
        prices = _FASTENER_PRICES[ft]
        base = prices.get(mat_fam, prices.get("default", 0.10))

        # Size adjustment
        ts = specs.get("thread_size", "")
        m_num = re.search(r"M(\d+)", ts)
        if m_num:
            size = int(m_num.group(1))
            base *= (1 + (size - 6) * 0.08) if size > 6 else 1.0

        # Length adjustment
        ln = specs.get("length_mm", 20)
        base *= (1 + (ln - 20) * 0.003) if ln > 20 else 1.0

        # Grade adjustment
        grade = specs.get("bolt_grade", "")
        if grade in ("10.9", "12.9"):
            base *= 1.5
        elif grade == "8.8":
            base *= 1.2

        # Volume discount
        if quantity >= 1000:
            base *= 0.6
        elif quantity >= 100:
            base *= 0.75

        result["unit_price"] = round(max(0.01, base), 4)
        result["confidence"] = "medium"
        result["source"] = "parametric"
        result["lead_days"] = 7
        return result

    # 3) Electronic component parametric pricing
    ctype = specs.get("component_type", "")
    base_info = _COMPONENT_BASE_PRICES.get(ctype, {"base": 0.50})
    price = base_info["base"]

    # Adjust by specs
    if ctype == "resistor":
        pw = specs.get("power_w", 0.125)
        price += base_info.get("per_power_w", 0) * pw
        tol = specs.get("tolerance_pct", 5)
        if tol <= 1:
            price *= base_info.get("precision_mult", 2.0)
    elif ctype == "capacitor":
        cf = specs.get("capacitance_f", 1e-7)
        cf_uf = cf * 1e6
        price += base_info.get("per_uf", 0) * cf_uf
        vv = specs.get("voltage_v", 16)
        price += base_info.get("voltage_mult", 0) * vv
    elif ctype == "microcontroller":
        price = base_info["base"]  # MCUs vary wildly; keep baseline
    elif ctype == "connector":
        price = base_info["base"]

    # Package premium
    pkg = specs.get("package", "")
    if pkg in ("0201", "01005"):
        price *= 1.3
    elif pkg and any(x in pkg.upper() for x in ("BGA", "QFN", "LQFP")):
        price *= 1.5

    # Volume discount
    if quantity >= 10000:
        price *= 0.3
    elif quantity >= 1000:
        price *= 0.5
    elif quantity >= 100:
        price *= 0.7

    result["unit_price"] = round(max(0.001, price), 4)
    result["confidence"] = "medium" if ctype else "low"
    result["source"] = "parametric"
    result["lead_days"] = 14
    result["moq"] = _estimate_moq(ctype, quantity)

    return result


def _estimate_moq(ctype: str, qty: int) -> int:
    if ctype in ("resistor", "capacitor", "inductor"):
        return max(10, min(qty, 100))
    return max(1, min(qty, 50))


def _query_octopart(mpn: str) -> Optional[Dict]:
    """
    Query Octopart API for real pricing data.
    Returns None if API key not configured or query fails.
    """
    if not OCTOPART_API_KEY:
        logger.debug(f"Octopart API key not set — skipping API lookup for {mpn}")
        return None

    try:
        import urllib.request
        import json
        url = f"https://octopart.com/api/v4/rest/parts/match?apikey={OCTOPART_API_KEY}&queries=[{{'mpn':'{mpn}'}}]"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [{}])[0].get("items", [])
            if results:
                item = results[0]
                offers = item.get("offers", [])
                best = None
                for o in offers:
                    prices = o.get("prices", {}).get("USD", [])
                    if prices:
                        p = float(prices[0][1])
                        if best is None or p < best["unit_price"]:
                            best = {
                                "unit_price": round(p, 4),
                                "supplier": o.get("seller", {}).get("name", ""),
                                "stock": o.get("in_stock_quantity", 0),
                                "lead_days": o.get("factory_lead_days", 14),
                                "moq": o.get("moq", 1) or 1,
                            }
                return best
    except Exception as e:
        logger.warning(f"Octopart API failed for '{mpn}': {e}")

    return None


# ══════════════════════════════════════════════════════════
# RAW MATERIAL PRICING
# ══════════════════════════════════════════════════════════

def price_raw_material(specs: Dict[str, Any], quantity: int = 1, region: str = "local") -> Dict[str, Any]:
    """Price raw material using commodity baselines + regional multiplier."""
    family = specs.get("material_family", "carbon_steel")
    base_per_kg = _COMMODITY_PRICES.get(family, 1.50)

    # Regional adjustment
    mult = _REGION_MULT.get(region, 1.0)
    adjusted = base_per_kg * mult

    # Processing surcharge (cut, polish, etc.)
    form = specs.get("form", "bar")
    form_surcharge = {"sheet": 0.30, "plate": 0.25, "rod": 0.15, "tube": 0.40,
                      "coil": 0.10, "wire": 0.20, "billet": 0.05}.get(form, 0.15)
    adjusted += form_surcharge

    # Estimate weight per piece (rough — ideally from dimensions)
    dims = specs.get("dimensions_mm", [])
    dia = specs.get("diameter_mm", 0)
    thickness = specs.get("thickness_mm", 0)

    est_kg = 0.5  # default
    if dims and len(dims) >= 2:
        vol_mm3 = dims[0] * dims[1] * (dims[2] if len(dims) > 2 else (thickness or 5))
        density = {"stainless_steel": 8.0, "carbon_steel": 7.85, "aluminum": 2.7,
                    "copper": 8.96, "brass": 8.5, "plastic": 1.2, "titanium": 4.5}.get(family, 7.0)
        est_kg = vol_mm3 * density / 1e6  # mm3 → cm3 → kg
    elif dia > 0:
        length = specs.get("length_mm", 100)
        vol_mm3 = math.pi * (dia / 2) ** 2 * length
        density = 7.85 if "steel" in family else 2.7
        est_kg = vol_mm3 * density / 1e6

    cost_per_piece = adjusted * max(0.01, est_kg)

    return {
        "source": "commodity_estimate",
        "base_per_kg": round(base_per_kg, 2),
        "regional_adjusted_per_kg": round(adjusted, 2),
        "estimated_weight_kg": round(est_kg, 3),
        "cost_per_piece": round(cost_per_piece, 2),
        "total_cost": round(cost_per_piece * quantity, 2),
        "region": region,
        "currency": "USD",
        "confidence": "medium",
    }


# ══════════════════════════════════════════════════════════
# CUSTOM / MACHINED COMPONENT ESTIMATION
# ══════════════════════════════════════════════════════════

def estimate_custom_component(specs: Dict[str, Any], category_info: Dict[str, Any] = None,
                               quantity: int = 1, region: str = "local") -> Dict[str, Any]:
    """
    Estimate custom/machined component — returns process info and complexity.
    ❌ Does NOT return unit price or total price.
    ✅ Returns material cost, machining time, complexity score.
    """
    cat = category_info or {}
    material_family = specs.get("material_family", "carbon_steel")
    geometry = cat.get("geometry", "prismatic")
    tolerance = cat.get("tolerance", "standard")
    mat_form = cat.get("material_form", "billet")

    # Material cost estimation
    base_kg_price = _COMMODITY_PRICES.get(material_family, 1.50)
    est_kg = 0.5  # default rough stock weight
    dims = specs.get("dimensions_mm", [])
    if dims and len(dims) >= 2:
        vol = dims[0] * dims[1] * (dims[2] if len(dims) > 2 else 20)
        density = {"stainless_steel": 8.0, "aluminum": 2.7, "plastic": 1.2}.get(material_family, 7.5)
        est_kg = vol * density / 1e6 * 1.3  # 30% buy-to-fly

    material_cost = base_kg_price * est_kg

    # Complexity scoring
    complexity_factors = 0
    if geometry in ("3d", "multi_axis"):
        complexity_factors += 2
    elif geometry == "2.5d":
        complexity_factors += 1

    if tolerance in ("precision", "ultra"):
        complexity_factors += 2
    elif tolerance == "standard":
        complexity_factors += 1

    sec_ops = cat.get("secondary_ops", [])
    complexity_factors += len(sec_ops)

    if complexity_factors <= 2:
        complexity = "low"
    elif complexity_factors <= 5:
        complexity = "medium"
    else:
        complexity = "high"

    # Process selection
    process = "CNC Milling"
    if mat_form == "sheet":
        process = "Sheet Metal (Laser + Bend)"
    elif mat_form == "polymer":
        process = "Injection Molding" if quantity > 1000 else "CNC Machining"
    elif geometry in ("3d", "multi_axis"):
        process = "5-Axis CNC"
    elif any("turn" in str(o) for o in sec_ops):
        process = "CNC Turning"

    # Geometry type
    geo_type = "sheet_metal" if mat_form == "sheet" else ("injection" if "injection" in process.lower() else "cnc")

    # Machining time estimate (hours per part)
    time_mult = {"low": 0.3, "medium": 0.8, "high": 1.5}[complexity]
    machining_hrs = round(time_mult * (1.5 if geo_type == "cnc" else 0.3), 2)

    # Machine rate for region
    rate = _MACHINE_RATES.get(region, 60)

    return {
        "part_type": "custom",
        "material": specs.get("material_name") or specs.get("material_grade") or material_family,
        "material_cost_est": round(material_cost, 2),
        "geometry_type": geo_type,
        "manufacturing_process": process,
        "complexity": complexity,
        "machining_time_hrs": machining_hrs,
        "machine_rate_hr": rate,
        "region": region,
        "quantity": quantity,
        "confidence": "estimate",
        # ❌ NO unit_price or total_price for custom parts
    }


# ══════════════════════════════════════════════════════════
# UNIFIED PRICING FUNCTION
# ══════════════════════════════════════════════════════════

def price_item(specs: Dict[str, Any], category: str, mpn: str = "",
               quantity: int = 1, region: str = "local",
               category_info: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Unified pricing entry point.
    Routes to correct pricing engine based on category.
    """
    if category == "standard":
        return price_standard_component(specs, mpn=mpn, quantity=quantity)
    elif category == "raw_material":
        return price_raw_material(specs, quantity=quantity, region=region)
    elif category == "custom":
        return estimate_custom_component(specs, category_info=category_info,
                                          quantity=quantity, region=region)
    else:
        return price_standard_component(specs, mpn=mpn, quantity=quantity)
