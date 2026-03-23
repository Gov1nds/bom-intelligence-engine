"""
BOM Intelligence Engine — main.py (v3 — Pure Function Service)

ONLY: Parse BOM → Classify → Extract Specs → Return JSON
NO: Pricing, decisions, memory, reporting, external APIs
"""
import sys, os, shutil, uuid, logging
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent))
from engine.orchestrator import BOMIntelligenceEngine

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

app = FastAPI(title="BOM Intelligence Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path("uploads").mkdir(exist_ok=True)
engine = BOMIntelligenceEngine()


def verify_internal_key(request: Request):
    if INTERNAL_API_KEY:
        key = request.headers.get("X-Internal-Key", "")
        if key != INTERNAL_API_KEY:
            raise HTTPException(403, "Invalid internal key")


@app.get("/")
def root():
    return {
        "service": "BOM Intelligence Engine",
        "version": "3.0.0",
        "status": "ok",
        "capabilities": ["parse", "normalize", "classify", "extract_specs"],
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
        result = engine.run_pipeline(str(sp), user_location, target_currency)
        return JSONResponse(content=result)
    finally:
        sp.unlink(missing_ok=True)