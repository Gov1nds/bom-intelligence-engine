"""
End-to-end integration test.
Loads sample BOM → runs full pipeline → validates output structure and values.
Run: python tests/test_e2e.py
"""
import sys, os, csv, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE = [
    {"part_name":"Res 10k 5% 0402","quantity":"500","manufacturer":"Yageo","mpn":"RC0402FR-0710KL"},
    {"part_name":"Cap 100nF 16V 0603","quantity":"500","manufacturer":"Murata","mpn":"GRM188R61C104KA01D"},
    {"part_name":"STM32F407VGT6","quantity":"50","manufacturer":"STMicroelectronics","mpn":"STM32F407VGT6"},
    {"part_name":"USB-C Connector 24pin","quantity":"50","manufacturer":"Molex","mpn":"2171750001"},
    {"part_name":"Custom Bracket Aluminum 6061-T6 CNC Machined","quantity":"100","material":"Aluminum 6061-T6","notes":"As per drawing, ±0.05mm"},
    {"part_name":"Steel Shaft 20mm OD Precision Ground","quantity":"100","material":"Carbon Steel 1045","notes":"±0.01mm"},
    {"part_name":"Aluminum Sheet 3mm 5052-H32 1000x500mm","quantity":"25","material":"Aluminum 5052-H32"},
    {"part_name":"Custom Housing ABS Injection Molded","quantity":"5000","material":"ABS Plastic","notes":"Complex 3D, snap fits"},
    {"part_name":"PCB Assembly 4-layer FR4","quantity":"50","notes":"4-layer 1.6mm HASL"},
    {"part_name":"M5x20 Hex Bolt SS304","quantity":"1000"},
    {"part_name":"Copper Bar Stock 25mm","quantity":"10","material":"Copper C110"},
    {"part_name":"LED Red 0805 SMD","quantity":"500","manufacturer":"Vishay"},
    {"part_name":"Custom Sheet Metal Bracket Stainless Steel","quantity":"200","material":"SS304","notes":"Laser cut + 2 bends"},
    {"part_name":"Bearing 6205-2RS","quantity":"50","manufacturer":"SKF","mpn":"6205-2RS"},
    {"part_name":"Nylon Spacer M4 10mm","quantity":"200","material":"Nylon 6/6"},
]

def write_csv(path):
    fields = ["part_name","quantity","manufacturer","mpn","material","notes"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in SAMPLE: w.writerow({k: r.get(k,"") for k in fields})

def main():
    # --- Setup: clean memory, write sample CSV ---
    from engine.orchestrator import BOMIntelligenceEngine
    from engine.memory.memory_store import PricingMemory, SupplierMemory, DecisionMemory

    tmpdir = tempfile.mkdtemp()
    csv_path = os.path.join(tmpdir, "sample_bom.csv")
    write_csv(csv_path)

    engine = BOMIntelligenceEngine()
    engine.pm = PricingMemory(os.path.join(tmpdir, "p.json"))
    engine.sm = SupplierMemory(os.path.join(tmpdir, "s.json"))
    engine.dm = DecisionMemory(os.path.join(tmpdir, "d.json"))

    errors = []
    def check(cond, msg):
        if not cond: errors.append(msg)

    # --- Run full pipeline ---
    report = engine.run_pipeline(csv_path, "Bangalore, India", "USD")

    # --- Validate top-level keys ---
    required_keys = [
        "section_1_executive_summary",
        "section_2_component_breakdown",
        "section_3_sourcing_strategy",
        "section_4_financial",
        "section_5_recommendation",
        "section_6_learning_snapshot",
        "_meta",
    ]
    for k in required_keys:
        check(k in report, f"Missing top-level key: {k}")

    # --- Section 1: Executive Summary ---
    s1 = report.get("section_1_executive_summary", {})
    check(isinstance(s1.get("total_cost"), (int, float)), "total_cost must be numeric")
    check(s1.get("total_cost", 0) > 0, "total_cost must be > 0")
    check("cost_breakdown" in s1, "Missing cost_breakdown")
    bd = s1.get("cost_breakdown", {})
    for field in ["material", "manufacturing", "logistics", "tariffs", "nre"]:
        check(field in bd, f"Missing cost_breakdown.{field}")
        check(isinstance(bd.get(field), (int, float)), f"cost_breakdown.{field} must be numeric")
    check("lead_time" in s1, "Missing lead_time")
    lt = s1.get("lead_time", {})
    check(lt.get("min_days", 0) > 0, "min_days > 0")
    check(lt.get("max_days", 0) >= lt.get("min_days", 0), "max_days >= min_days")
    check(isinstance(s1.get("risk_score"), (int, float)), "risk_score must be numeric")
    check("optimization" in s1, "Missing optimization")
    check("decision_distribution" in s1, "Missing decision_distribution")

    # --- Section 2: Component Breakdown ---
    s2 = report.get("section_2_component_breakdown", [])
    check(isinstance(s2, list), "section_2 must be a list")
    check(len(s2) == 15, f"Expected 15 items, got {len(s2)}")
    for i, item in enumerate(s2):
        check("item_id" in item, f"item[{i}] missing item_id")
        check("description" in item, f"item[{i}] missing description")
        check("quantity" in item, f"item[{i}] missing quantity")
        check("category" in item, f"item[{i}] missing category")
        check(item.get("category") in ("standard","raw_material","custom","unknown"), f"item[{i}] invalid category: {item.get('category')}")
        check("selected_vendor" in item, f"item[{i}] missing selected_vendor")
        check("decision_mode" in item, f"item[{i}] missing decision_mode")
        v = item.get("selected_vendor")
        if v:
            check(isinstance(v.get("simulated_tlc"), (int, float)), f"item[{i}] TLC must be numeric")
            check(v.get("simulated_tlc", 0) > 0, f"item[{i}] TLC must be > 0")
            check("region" in v, f"item[{i}] vendor missing region")
            check("tlc_breakdown" in v, f"item[{i}] vendor missing tlc_breakdown")
            check("process_chain" in v, f"item[{i}] vendor missing process_chain")
        check("explanation" in item, f"item[{i}] missing explanation")

    # --- Section 3: Sourcing Strategy ---
    s3 = report.get("section_3_sourcing_strategy", {})
    check("local_vs_offshore" in s3, "Missing local_vs_offshore")
    check("volume_strategy" in s3, "Missing volume_strategy")
    check("process_summary" in s3, "Missing process_summary")
    check(len(s3.get("process_summary", [])) >= 1, "At least 1 custom process summary")

    # --- Section 4: Financial ---
    s4 = report.get("section_4_financial", {})
    check("target_currency" in s4, "Missing target_currency")
    check("exchange_rates" in s4, "Missing exchange_rates")
    check(s4.get("target_currency") == "USD", "Currency should be USD")

    # --- Section 5: Recommendation ---
    s5 = report.get("section_5_recommendation", {})
    check(s5.get("optimal_cost", 0) > 0, "optimal_cost > 0")
    check("order_priority" in s5, "Missing order_priority")

    # --- Section 6: Learning Snapshot ---
    s6 = report.get("section_6_learning_snapshot", {})
    check("system_confidence" in s6, "Missing system_confidence")
    check("exploration_rate" in s6, "Missing exploration_rate")
    check("total_iterations" in s6, "Missing total_iterations")
    check(s6.get("total_iterations", 0) == 15, f"Expected 15 iterations, got {s6.get('total_iterations')}")

    # --- Meta ---
    meta = report.get("_meta", {})
    check(meta.get("items") == 15, f"Meta items should be 15, got {meta.get('items')}")
    check(meta.get("candidates", 0) > 0, "Meta candidates > 0")
    check(meta.get("total_time_s", 99) < 30, "Pipeline < 30s")

    # --- Classification distribution check ---
    categories = [item.get("category") for item in s2]
    check("standard" in categories, "At least one standard item")
    check("custom" in categories, "At least one custom item")
    check("raw_material" in categories, "At least one raw_material item")

    # --- Memory persisted ---
    state = engine.memory_state()
    check(state["suppliers"]["n"] > 0, "Suppliers tracked in memory")
    check(state["decision"]["iterations"] == 15, "Decision iterations = 15")

    # --- Report ---
    if errors:
        print(f"\nE2E TEST: {len(errors)} FAILURES")
        for e in errors:
            print(f"  FAIL: {e}")
        return 1
    else:
        print(f"\nE2E TEST: ALL PASSED")
        print(f"  Items: {meta.get('items')}")
        print(f"  Candidates: {meta.get('candidates')}")
        print(f"  Total cost: {s1.get('total_cost'):.2f} USD")
        print(f"  Lead time: {lt.get('min_days')}-{lt.get('max_days')} days")
        print(f"  Categories: {dict((c, categories.count(c)) for c in set(categories))}")
        print(f"  Time: {meta.get('total_time_s'):.3f}s")
        return 0

if __name__ == "__main__":
    sys.exit(main())
