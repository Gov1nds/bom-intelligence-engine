"""
BOM Intelligence Engine — main.py

Deploy (Railway/uvicorn):  uvicorn main:app --host 0.0.0.0 --port $PORT
CLI:                       python main.py --sample
"""
import sys, os, json, csv, shutil, uuid, tempfile, argparse, logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from engine.orchestrator import BOMIntelligenceEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# =========================================================
# FastAPI app — MODULE LEVEL (required for uvicorn main:app)
# =========================================================

app = FastAPI(title="BOM Intelligence Engine", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path("uploads").mkdir(exist_ok=True)
Path("data/memory").mkdir(parents=True, exist_ok=True)

engine = BOMIntelligenceEngine()

@app.get("/")
def root():
    return {
        "service": "BOM Intelligence Engine",
        "version": "2.0.0",
        "status": "ok",
        "memory": {
            "exploration_rate": engine.dm.exploration_rate,
            "confidence": engine.dm.confidence,
            "iterations": engine.dm.iterations,
        },
    }

@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.now().isoformat()}

@app.post("/api/analyze-bom")
async def analyze_bom(
    file: UploadFile = File(...),
    user_location: str = Form(""),
    target_currency: str = Form("USD"),
):
    sp = Path("uploads") / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with open(sp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        report = engine.run_pipeline(str(sp), user_location, target_currency)
        return JSONResponse(content=report)
    finally:
        sp.unlink(missing_ok=True)

@app.get("/api/memory")
def memory():
    return engine.memory_state()

# =========================================================
# CLI (only runs when called directly, not on import)
# =========================================================

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

def _write_csv(path, rows):
    fields = ["part_name","quantity","manufacturer","mpn","material","notes"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

def cli():
    parser = argparse.ArgumentParser(description="BOM Intelligence Engine")
    parser.add_argument("file", nargs="?", help="BOM file (.csv/.xlsx)")
    parser.add_argument("--sample", action="store_true", help="Use sample BOM")
    parser.add_argument("--location", default="", help="User location")
    parser.add_argument("--currency", default="USD", help="Target currency")
    parser.add_argument("--output", "-o", help="Save JSON report to file")
    parser.add_argument("--memory", action="store_true", help="Show memory state")
    parser.add_argument("--serve", action="store_true", help="Start uvicorn server")
    args = parser.parse_args()

    if args.memory:
        print(json.dumps(engine.memory_state(), indent=2))
        return

    if args.serve:
        import uvicorn
        port = int(os.getenv("PORT", "8000"))
        uvicorn.run(app, host="0.0.0.0", port=port)
        return

    if args.sample:
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        _write_csv(tmp.name, SAMPLE)
        tmp.close()
        fp = tmp.name
    elif args.file:
        fp = args.file
        if not Path(fp).exists():
            print(f"Not found: {fp}")
            sys.exit(1)
    else:
        parser.print_help()
        return

    try:
        print(f"\nBOM Intelligence Engine v2.0.0")
        print("=" * 60)
        report = engine.run_pipeline(fp, args.location, args.currency)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(report, f, indent=2, default=str)
            print(f"Report saved: {args.output}")
        else:
            s = report["section_1_executive_summary"]
            bd = s["cost_breakdown"]
            lt = s["lead_time"]
            opt = s["optimization"]
            dd = s["decision_distribution"]
            print(f"\n{'='*60}\nEXECUTIVE SUMMARY\n{'='*60}")
            print(f"Total Cost:      {s['total_cost']:>12,.2f} {args.currency}")
            print(f"  Manufacturing: {bd['manufacturing']:>12,.2f}")
            print(f"  Logistics:     {bd['logistics']:>12,.2f}")
            print(f"  Tariffs:       {bd['tariffs']:>12,.2f}")
            print(f"  NRE:           {bd['nre']:>12,.2f}")
            print(f"Lead Time:       {lt['min_days']}-{lt['max_days']} days (expected: {lt['expected_days']})")
            print(f"Risk Score:      {s['risk_score']:.3f}")
            print(f"Cost Savings:    {opt['cost_savings_pct']:.1f}%")
            print(f"Exploration:     {dd['exploration_pct']:.1f}%  |  Exploitation: {dd['exploitation_pct']:.1f}%")
            m = report["_meta"]
            print(f"\nProcessed {m['items']} items, {m['candidates']} candidates in {m['total_time_s']:.3f}s")
            print(f"\n{'='*60}\nCOMPONENT DECISIONS\n{'='*60}")
            for item in report["section_2_component_breakdown"]:
                v = item.get("selected_vendor", {})
                if v:
                    print(f"  {item['description'][:48]:48s} Q={item['quantity']:>5d}  TLC={v['simulated_tlc']:>10,.2f}  {item['decision_mode']:12s}  {v['region']}")
            ls = report["section_6_learning_snapshot"]
            print(f"\n{'='*60}\nLEARNING\n{'='*60}")
            print(f"Confidence: {ls['system_confidence']:.3f}  |  Explore rate: {ls['exploration_rate']:.4f}  |  Iterations: {ls['total_iterations']}")
    finally:
        if args.sample and os.path.exists(fp):
            os.unlink(fp)

if __name__ == "__main__":
    cli()
