"""
BOM Intelligence Engine — main.py (v3 — Pure Function Service)

ONLY: Parse BOM → Classify → Extract Specs → Return JSON
NO: Pricing, decisions, memory, reporting, external APIs
"""

import asyncio
import logging
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent))

from engine.orchestrator import BOMIntelligenceEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "").strip()


def verify_internal_key(x_internal_key: str = Header(default="")) -> None:
    if not INTERNAL_API_KEY:
        return

    if not x_internal_key or x_internal_key.strip() != INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_INTERNAL_KEY",
                "message": "Unauthorized internal request",
            },
        )


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


@app.post("/api/analyze-bom", dependencies=[Depends(verify_internal_key)])
async def analyze_bom(
    file: UploadFile = File(...),
    user_location: str = Form(""),
    target_currency: str = Form("USD"),
):
    file_path = None
    try:
        file_name = file.filename or f"bom_{uuid.uuid4().hex}.bin"
        safe_name = file_name.replace("/", "_").replace("\\", "_")
        file_path = f"uploads/{uuid.uuid4()}_{safe_name}"

        with open(file_path, "wb") as f:
            f.write(await file.read())

        result = await asyncio.to_thread(
            engine.run_pipeline,
            file_path,
            user_location,
            target_currency,
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ENGINE_FAILED",
                "message": str(e),
            },
        )
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass