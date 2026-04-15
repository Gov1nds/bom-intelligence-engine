"""Total Landed Cost computation per FIN-003, PC-004.

TLC = (C_mfg × Q) + C_nre + C_log + (C_mfg × Q × T) + C_fx
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from core.schemas import Money, TLCBreakdown


def _d(val: str | float | int | None) -> Decimal:
    try:
        return Decimal(str(val)) if val is not None else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def compute_tlc(
    vendor,
    enrichment_data,
    project_context,
    currency: str = "USD",
) -> dict:
    """Compute Total Landed Cost for a vendor candidate."""
    c_mfg = _d(vendor.unit_price)
    q = _d(enrichment_data.quantity)
    c_nre = _d(vendor.tooling_cost)

    # Logistics
    c_log = Decimal(0)
    if enrichment_data.logistics_enrichment and enrichment_data.logistics_enrichment.freight_estimate:
        c_log = _d(enrichment_data.logistics_enrichment.freight_estimate.amount)

    # Tariff
    tariff_rate = Decimal(0)
    if enrichment_data.tariff_enrichment:
        tariff_rate = _d(enrichment_data.tariff_enrichment.duty_rate_pct) / 100

    # Forex adjustment (stub: 0 for same-currency, 2% for cross-currency)
    c_fx = Decimal(0)
    if vendor.currency and vendor.currency != currency:
        c_fx = c_mfg * q * Decimal("0.02")

    manufacturing = c_mfg * q
    tariff_cost = manufacturing * tariff_rate
    total = manufacturing + c_nre + c_log + tariff_cost + c_fx

    def _money(val: Decimal) -> Money:
        return Money(amount=str(val.quantize(Decimal("0.01"))), currency=currency)

    return {
        "total": _money(total),
        "breakdown": TLCBreakdown(
            manufacturing=_money(manufacturing),
            nre=_money(c_nre),
            logistics=_money(c_log),
            tariff=_money(tariff_cost),
            forex_adjustment=_money(c_fx),
        ),
        "crossover_quantity": None,
    }
