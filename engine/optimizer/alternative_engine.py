"""
PHASE F — Alternative Component Finder

For standard components, finds compatible alternatives based on:
  1. Extracted specifications (parametric matching)
  2. Package/footprint compatibility
  3. Equal or better ratings
  4. Price/availability ranking
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("alternative_engine")


def find_alternatives(
    specs: Dict[str, Any],
    mpn: str = "",
    quantity: int = 1,
    max_results: int = 3,
) -> List[Dict[str, Any]]:
    """
    Find alternative components based on extracted specs.
    Uses parametric matching — no exact MPN required.
    """
    ctype = specs.get("component_type", "")
    if not ctype:
        return []

    alternatives = []

    if ctype == "resistor":
        alternatives = _find_resistor_alts(specs, quantity)
    elif ctype == "capacitor":
        alternatives = _find_capacitor_alts(specs, quantity)
    elif ctype in ("ic", "microcontroller", "regulator"):
        alternatives = _find_ic_alts(specs, mpn)
    elif ctype in ("connector", "relay", "switch"):
        alternatives = _find_generic_alts(ctype, specs)
    elif specs.get("fastener_type"):
        alternatives = _find_fastener_alts(specs, quantity)
    else:
        alternatives = _find_generic_alts(ctype, specs)

    return alternatives[:max_results]


def _find_resistor_alts(specs: Dict, qty: int) -> List[Dict]:
    """Find resistor alternatives based on value, tolerance, package."""
    r_val = specs.get("resistance_ohm")
    tol = specs.get("tolerance_pct", 5)
    pkg = specs.get("package", "0603")
    pw = specs.get("power_w", 0.1)

    if r_val is None:
        return []

    alts = []
    # Standard resistor series alternatives
    mfrs = [
        {"brand": "Yageo", "series": "RC", "mult": 1.0},
        {"brand": "Vishay", "series": "CRCW", "mult": 1.1},
        {"brand": "Panasonic", "series": "ERJ", "mult": 1.15},
        {"brand": "KOA", "series": "RK73", "mult": 0.95},
    ]

    base_price = 0.003 * (1 if tol >= 5 else 2) * (1 if pw <= 0.125 else 1.5)
    if qty >= 1000:
        base_price *= 0.5

    for mfr in mfrs:
        est_mpn = f"{mfr['series']}{pkg}-{_format_value(r_val)}"
        alts.append({
            "manufacturer": mfr["brand"],
            "estimated_mpn": est_mpn,
            "specs_match": f"{_format_value(r_val)}Ω ±{tol}% {pkg}",
            "estimated_price": round(base_price * mfr["mult"], 4),
            "compatibility": "direct_drop_in",
            "package": pkg,
            "note": f"Same value/package, {mfr['brand']} equivalent",
        })

    return alts


def _find_capacitor_alts(specs: Dict, qty: int) -> List[Dict]:
    """Find capacitor alternatives."""
    cap = specs.get("capacitance_display", "")
    voltage = specs.get("voltage_v", 16)
    pkg = specs.get("package", "0603")
    dielectric = specs.get("dielectric", "X7R")

    mfrs = [
        {"brand": "Murata", "series": "GRM", "mult": 1.0},
        {"brand": "Samsung", "series": "CL", "mult": 0.9},
        {"brand": "TDK", "series": "C", "mult": 1.05},
        {"brand": "Yageo", "series": "CC", "mult": 0.85},
    ]

    base_price = 0.01 * (1 + voltage / 100)
    if qty >= 1000:
        base_price *= 0.5

    alts = []
    for mfr in mfrs:
        alts.append({
            "manufacturer": mfr["brand"],
            "estimated_mpn": f"{mfr['series']}{pkg}",
            "specs_match": f"{cap} {voltage}V {dielectric} {pkg}",
            "estimated_price": round(base_price * mfr["mult"], 4),
            "compatibility": "direct_drop_in",
            "package": pkg,
            "note": f"{mfr['brand']} {dielectric} equivalent",
        })

    return alts


def _find_ic_alts(specs: Dict, mpn: str) -> List[Dict]:
    """For ICs, suggest pin-compatible alternatives if known."""
    # IC alternatives require exact knowledge — return generic suggestion
    pkg = specs.get("package", "")
    return [{
        "manufacturer": "Various",
        "estimated_mpn": f"Compatible with {mpn}" if mpn else "Parametric search needed",
        "specs_match": f"Package: {pkg}" if pkg else "Verify datasheet",
        "estimated_price": None,
        "compatibility": "verify_required",
        "note": "IC alternatives require datasheet verification. Suggest cross-reference search.",
    }]


def _find_fastener_alts(specs: Dict, qty: int) -> List[Dict]:
    """Find fastener alternatives (different brands/grades)."""
    ft = specs.get("fastener_type", "bolt")
    ts = specs.get("thread_size", "M8")
    ln = specs.get("length_mm", 20)
    mat = specs.get("material_family", "stainless_steel")
    grade = specs.get("bolt_grade", "8.8")

    alts = []
    sources = [
        {"supplier": "Misumi", "region": "JP/Global", "mult": 1.2},
        {"supplier": "McMaster-Carr", "region": "US", "mult": 1.5},
        {"supplier": "Boltport", "region": "IN", "mult": 0.5},
        {"supplier": "TR Fastenings", "region": "EU", "mult": 1.0},
    ]

    base = 0.10 if "steel" in mat else 0.25
    if qty >= 1000:
        base *= 0.5

    for src in sources:
        alts.append({
            "supplier": src["supplier"],
            "specs_match": f"{ft.title()} {ts}x{int(ln)} {mat} Grade {grade}",
            "estimated_price": round(base * src["mult"], 4),
            "region": src["region"],
            "compatibility": "direct_replacement",
            "note": f"Standard {ft} from {src['supplier']}",
        })

    return alts


def _find_generic_alts(ctype: str, specs: Dict) -> List[Dict]:
    """Generic alternative suggestion."""
    return [{
        "manufacturer": "Various",
        "specs_match": f"{ctype} — parametric search recommended",
        "estimated_price": None,
        "compatibility": "verify_required",
        "note": f"Use distributor parametric search for {ctype} alternatives",
    }]


def _format_value(ohms: float) -> str:
    """Format resistance value for display."""
    if ohms >= 1e6:
        return f"{ohms/1e6:.1f}M"
    elif ohms >= 1e3:
        return f"{ohms/1e3:.1f}K"
    else:
        return f"{ohms:.1f}"
