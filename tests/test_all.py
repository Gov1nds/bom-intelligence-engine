"""
Test Suite — validates all 7 phases end-to-end.
Run: python tests/test_all.py
"""
import sys, os, csv, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ingestion.normalizer import process_bom, normalize_text
from engine.classification.classifier import classify_item, classify_bom
from engine.sourcing.sourcing_engine import generate_candidate_strategies, select_process_chain
from engine.decision.rl_engine import select_optimal_strategy
from engine.reporting.report_engine import generate_full_report
from engine.feedback.feedback_engine import ExecutionTracker, compute_feedback, update_memory
from engine.memory.memory_store import PricingMemory, SupplierMemory, DecisionMemory
from engine.integrations.currency_engine import get_exchange_rates, convert
from engine.orchestrator import BOMIntelligenceEngine
from core.schemas import *

P = F = 0
def ok(cond, msg=""):
    global P, F
    if cond: P += 1
    else: F += 1; print(f"  FAIL: {msg}")
def eq(a, b, msg=""): ok(a == b, f"{msg} — got {a!r}, expected {b!r}")

def _csv(rows):
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="")
    fields = ["part_name","quantity","manufacturer","mpn","material","notes"]
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
    for r in rows: w.writerow({k: r.get(k,"") for k in fields})
    f.close(); return f.name

def _tmpdir(): return tempfile.mkdtemp()

SAMPLE = [
    {"part_name":"Res 10k 5% 0402","quantity":"100","manufacturer":"Yageo","mpn":"RC0402FR-0710KL"},
    {"part_name":"Custom Bracket CNC Aluminum","quantity":"50","material":"Aluminum 6061","notes":"±0.05mm"},
    {"part_name":"Aluminum Sheet 3mm 5052","quantity":"10","material":"Aluminum 5052"},
    {"part_name":"STM32F407VGT6","quantity":"25","manufacturer":"STMicroelectronics","mpn":"STM32F407VGT6"},
    {"part_name":"M5x20 Hex Bolt SS304","quantity":"500"},
]

# ============ PHASE 1 ============
def test_p1():
    print("\n=== Phase 1: Ingestion ===")
    ok("resistor" in normalize_text("Res 100"), "Res→resistor")
    ok("capacitor" in normalize_text("Cap 100nF"), "Cap→capacitor")
    ok("stainless_steel" in normalize_text("SS 304 Sheet"), "SS→stainless_steel")
    ok("metric_bolt_M5x20" in normalize_text("M5x20 Bolt"), "M5x20→metric_bolt")
    ok("10000" in normalize_text("R 10k"), "10k→10000")
    # No double words
    r = normalize_text("Cap 100nF 16V")
    ok(r.count("capacitor") <= 1, f"No double capacitor: {r!r}")
    # CSV parse
    fp = _csv(SAMPLE)
    items = process_bom(fp)
    eq(len(items), 5, "5 items parsed")
    ok(items[0].mpn == "RC0402FR-0710KL", "MPN extracted")
    ok(items[0].manufacturer == "Yageo", "Manufacturer extracted")
    eq(items[0].quantity, 100, "Quantity parsed")
    os.unlink(fp)

# ============ PHASE 2 ============
def test_p2():
    print("\n=== Phase 2: Classification ===")
    # MPN + Brand → STANDARD
    c = classify_item(NormalizedBOMItem(standard_text="resistor 10k",mpn="RC0402FR",manufacturer="Yageo"))
    eq(c.category, PartCategory.STANDARD, "MPN+Brand→STANDARD")
    eq(c.classification_path, ClassificationPath.PATH_3_1, "Path 3_1")
    ok(c.confidence >= 0.85, "High confidence")
    # Empty manufacturer must NOT match brand
    c2 = classify_item(NormalizedBOMItem(standard_text="custom bracket cnc",manufacturer="",material="aluminum"))
    ok(c2.has_brand == False, "Empty mfr → no brand match")
    eq(c2.category, PartCategory.CUSTOM, "Custom bracket→CUSTOM")
    # Raw material
    c3 = classify_item(NormalizedBOMItem(standard_text="aluminum sheet 3mm",material="aluminum 5052"))
    eq(c3.category, PartCategory.RAW_MATERIAL, "Al sheet→RAW")
    eq(c3.classification_path, ClassificationPath.PATH_3_2, "Path 3_2")
    # Custom with ABS (was broken: abs matched RAW before CUSTOM)
    c4 = classify_item(NormalizedBOMItem(standard_text="custom housing abs injection molded",material="abs plastic"))
    eq(c4.category, PartCategory.CUSTOM, "Custom housing ABS→CUSTOM")
    # Generic standard
    c5 = classify_item(NormalizedBOMItem(standard_text="metric_bolt_M5x20 hex_bolt ss304"))
    eq(c5.category, PartCategory.STANDARD, "Bolt→STANDARD")
    # Copper bar → RAW
    c6 = classify_item(NormalizedBOMItem(standard_text="copper bar stock 25mm",material="copper c110"))
    eq(c6.category, PartCategory.RAW_MATERIAL, "Copper bar→RAW")
    # Unknown fallback
    c7 = classify_item(NormalizedBOMItem(standard_text="xyz widget 123"))
    ok(c7.confidence <= 0.5, "Unknown → low confidence")
    # Batch
    fp = _csv(SAMPLE); items = process_bom(fp)
    classified = classify_bom(items)
    eq(len(classified), 5, "All classified")
    cats = [c.category.value for c in classified]
    ok("standard" in cats, "Has standard"); ok("custom" in cats, "Has custom")
    os.unlink(fp)

# ============ PHASE 3 ============
def test_p3():
    print("\n=== Phase 3: Sourcing ===")
    d = _tmpdir()
    sm = SupplierMemory(os.path.join(d,"s.json")); pm = PricingMemory(os.path.join(d,"p.json"))
    fp = _csv(SAMPLE); items = process_bom(fp); classified = classify_bom(items)
    cands = generate_candidate_strategies(classified, "Mumbai, India", sm, pm)
    ok(len(cands) == 5, f"5 items have candidates: {len(cands)}")
    total = sum(len(v) for v in cands.values())
    ok(total >= 40, f"At least 40 candidates: {total}")
    # TLC must be positive and industrial >= base
    for item_cands in cands.values():
        for c in item_cands:
            ok(c.simulated_tlc > 0, f"TLC>0 for {c.supplier_id}")
            ok(c.tlc.industrial_tlc >= c.tlc.base_tlc, "Industrial≥Base")
            ok(c.risk_adjusted_tlc >= c.simulated_tlc, "Risk-adj≥Simulated")
    # Process chain for custom items
    custom = [c for c in classified if c.category == PartCategory.CUSTOM]
    if custom:
        chain = select_process_chain(custom[0])
        ok(len(chain) > 0, f"Process chain generated: {[p.value for p in chain]}")
    os.unlink(fp)

# ============ PHASE 4 ============
def test_p4():
    print("\n=== Phase 4: Decision Engine ===")
    d = _tmpdir()
    sm = SupplierMemory(os.path.join(d,"s.json")); dm = DecisionMemory(os.path.join(d,"d.json"))
    # Build test candidates
    cands = []
    for i in range(5):
        c = SourcingCandidate(item_id="T1",supplier_id=f"sup_{i}",supplier_name=f"Sup-{i}",
                              region=["US","CN","IN","EU","VN"][i],unit_price=10+i*5,
                              quoted_lead_days=5+i*5,expected_lead_days=5+i*5,
                              simulated_tlc=1000+i*200,risk_adjusted_tlc=1100+i*250,
                              uncertainty_score=0.3+i*0.1,historical_variance=0.2+i*0.1,
                              reliability_score=0.9-i*0.05,transport_mode=TransportMode.SEA,
                              tlc=TLCBreakdown(c_mfg=10+i*5,quantity=100,c_log=50,c_nre=0,tariff_rate=0.05,c_compliance=20))
        c.tlc.compute(); cands.append(c)
    item = ClassifiedItem(item_id="T1",standard_text="test",quantity=100,category=PartCategory.STANDARD)
    dec = select_optimal_strategy(item, cands, sm, dm)
    ok(dec.selected is not None, "Has selection")
    ok(dec.decision_mode in (DecisionMode.EXPLORATION,DecisionMode.EXPLOITATION,DecisionMode.THOMPSON), "Valid mode")
    ok(len(dec.alternatives) > 0, "Has alternatives")
    ok(dec.score > 0, "Score>0")
    ok(len(dec.explanation.ucb_formula_used) > 0, "UCB formula documented")
    ok(len(dec.explanation.tlc_proof) > 0, "TLC proof documented")
    # Run 10 more to check iteration tracking
    for _ in range(10): select_optimal_strategy(item, cands, sm, dm)
    ok(dm.iterations >= 11, f"Iterations tracked: {dm.iterations}")

# ============ PHASE 5 ============
def test_p5():
    print("\n=== Phase 5: Reporting ===")
    d = _tmpdir()
    sm = SupplierMemory(os.path.join(d,"s.json")); dm = DecisionMemory(os.path.join(d,"d.json"))
    pm = PricingMemory(os.path.join(d,"p.json"))
    fp = _csv(SAMPLE); items = process_bom(fp); classified = classify_bom(items)
    cands = generate_candidate_strategies(classified, "", sm, pm)
    decisions = [select_optimal_strategy(ci, cands.get(ci.item_id,[]), sm, dm) for ci in classified]
    rates = get_exchange_rates("USD")
    report = generate_full_report(classified, decisions, "", "USD", sm, dm, pm, rates)
    for i in range(1,7):
        k = [x for x in report if x.startswith(f"section_{i}")]
        ok(len(k)==1, f"Section {i} present")
    s1 = report["section_1_executive_summary"]
    ok(s1["total_cost"] > 0, "Total cost>0")
    ok(isinstance(s1["total_cost"], float), "Total cost is float")
    ok("cost_breakdown" in s1, "Has breakdown")
    ok("lead_time" in s1, "Has lead time")
    s2 = report["section_2_component_breakdown"]
    eq(len(s2), 5, "5 items in breakdown")
    s3 = report["section_3_sourcing_strategy"]
    ok("local_vs_offshore" in s3, "Has LvO"); ok("process_summary" in s3, "Has process")
    os.unlink(fp)

# ============ PHASE 6+7 ============
def test_p67():
    print("\n=== Phase 6+7: Tracking & Feedback ===")
    d = _tmpdir()
    tracker = ExecutionTracker(os.path.join(d,"t.json"))
    sm = SupplierMemory(os.path.join(d,"s.json")); pm = PricingMemory(os.path.join(d,"p.json"))
    dm = DecisionMemory(os.path.join(d,"d.json"))
    tid = tracker.create("ITEM-1","ORD-1","sup_test",1000.0,14)
    ok(tid.startswith("TRK-"), "Tracking ID")
    tracker.milestone(tid,"T0",cost=0)
    tracker.milestone(tid,"T1",cost=200)
    tracker.milestone(tid,"T4",cost=850)
    rec = tracker.get(tid)
    ok(rec["completed"], "Completed at T4")
    ok(rec["actual_cost"] > 0, "Actual cost set")
    fb = compute_feedback(rec, best_cost=900)
    ok(fb.regret >= 0, "Regret≥0")
    update_memory(fb, sm, pm, dm, rec)
    s = sm.get("sup_test")
    ok(s is not None, "Supplier memory created")
    eq(s["orders"], 1, "Order counted")

# ============ MEMORY ============
def test_mem():
    print("\n=== Memory Persistence ===")
    d = _tmpdir()
    pm = PricingMemory(os.path.join(d,"p.json"))
    pm.update_price("r10k", 0.05, "test"); pm.update_commodity("copper", 8500); pm.save()
    pm2 = PricingMemory(os.path.join(d,"p.json"))
    ok(pm2.get_baseline("r10k") is not None, "Price persisted")
    eq(pm2.get_commodity("copper"), 8500, "Commodity persisted")
    sm = SupplierMemory(os.path.join(d,"s.json"))
    sm.update_from_feedback("supA",1100,1000,16,14,True,True); sm.save()
    sm2 = SupplierMemory(os.path.join(d,"s.json"))
    ok(sm2.exists("supA"), "Supplier persisted")
    eq(sm2.get("supA")["orders"], 1, "Orders counted")
    dm = DecisionMemory(os.path.join(d,"d.json"))
    dm.record("i","s","exploit",500,"US"); dm.add_regret("CN",50); dm.adapt_exploration(); dm.save()
    dm2 = DecisionMemory(os.path.join(d,"d.json"))
    eq(dm2.iterations, 1, "Iterations persisted")
    ok(dm2.region_regret("CN") == 50, "Regret persisted")

# ============ CURRENCY ============
def test_fx():
    print("\n=== Currency ===")
    rates = get_exchange_rates("USD")
    eq(rates["USD"], 1.0, "USD=1.0")
    ok(rates["EUR"] > 0, "EUR present")
    amt = convert(100, "USD", "EUR", rates)
    ok(amt > 0 and amt != 100, "Conversion works")
    rt = convert(amt, "EUR", "USD", rates)
    ok(abs(rt - 100) < 1, "Round-trip ≈ original")

# ============ E2E ============
def test_e2e():
    print("\n=== E2E Pipeline ===")
    d = _tmpdir()
    engine = BOMIntelligenceEngine()
    engine.pm = PricingMemory(os.path.join(d,"p.json"))
    engine.sm = SupplierMemory(os.path.join(d,"s.json"))
    engine.dm = DecisionMemory(os.path.join(d,"d.json"))
    fp = _csv(SAMPLE)
    report = engine.run_pipeline(fp, "Mumbai, India", "USD")
    ok("section_1_executive_summary" in report, "Has S1")
    ok("_meta" in report, "Has meta")
    m = report["_meta"]
    eq(m["items"], 5, "5 items")
    ok(m["candidates"] > 0, "Candidates>0")
    ok(m["total_time_s"] < 30, "Fast enough")
    # Run again — memory accumulates
    report2 = engine.run_pipeline(fp, "Mumbai, India", "USD")
    ok(engine.dm.iterations >= 10, f"Iterations accumulated: {engine.dm.iterations}")
    state = engine.memory_state()
    ok(state["suppliers"]["n"] > 0, "Suppliers tracked")
    os.unlink(fp)

if __name__ == "__main__":
    print("BOM Intelligence Engine — Test Suite")
    print("="*60)
    test_p1(); test_p2(); test_p3(); test_p4(); test_p5(); test_p67(); test_mem(); test_fx(); test_e2e()
    print(f"\n{'='*60}\n  RESULTS: {P} passed, {F} failed\n{'='*60}")
    sys.exit(1 if F else 0)
