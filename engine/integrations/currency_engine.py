"""Currency conversion with static fallback rates."""
from typing import Dict

RATES_TO_USD = {
    "USD":1.0,"EUR":1.09,"GBP":1.27,"INR":0.012,"CNY":0.138,"JPY":0.0067,
    "KRW":0.00075,"TWD":0.031,"VND":0.000041,"THB":0.028,"MXN":0.058,"SGD":0.74,
}

def get_exchange_rates(target: str = "USD") -> Dict[str, float]:
    t2u = RATES_TO_USD.get(target, 1.0)
    return {c: round(r/t2u, 6) if t2u else 1.0 for c, r in RATES_TO_USD.items()}

def convert(amount: float, frm: str, to: str, rates: Dict[str,float]=None) -> float:
    if frm == to: return amount
    if not rates: rates = get_exchange_rates(to)
    fr = rates.get(frm, 1.0); tr = rates.get(to, 1.0)
    return round(amount * tr / fr, 4) if fr else amount
