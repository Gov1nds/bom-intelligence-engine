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
UPLOAD_DIR = Path(os.getenv("BOM_ENGINE_UPLOAD_DIR", "uploads")).resolve()
ALLOW_ARBITRARY_PATH_INPUT = (
    os.getenv("BOM_ENGINE_ALLOW_ARBITRARY_PATH_INPUT", "false").strip().lower() == "true"
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
engine = BOMIntelligenceEngine()


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


def _safe_filename(file_name: str | None) -> str:
    candidate = (file_name or f"bom_{uuid.uuid4().hex}.bin").strip() or f"bom_{uuid.uuid4().hex}.bin"
    return candidate.replace("/", "_").replace("\\", "_")


def _persist_upload(upload: UploadFile) -> Path:
    file_name = _safe_filename(upload.filename)
    file_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file_name}"

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)

    return file_path


def _resolve_input_path(raw_path: str) -> Path:
    resolved = Path(raw_path).expanduser().resolve()

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INPUT_FILE_NOT_FOUND",
                "message": f"Input file does not exist: {raw_path}",
            },
        )

    if not ALLOW_ARBITRARY_PATH_INPUT:
        try:
            resolved.relative_to(UPLOAD_DIR)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "UNSAFE_INPUT_PATH",
                    "message": (
                        "Path input is restricted to the engine upload directory by default. "
                        "Set BOM_ENGINE_ALLOW_ARBITRARY_PATH_INPUT=true to allow other internal paths."
                    ),
                },
            )

    return resolved


async def _run_pipeline_async(
    file_path: Path,
    user_location: str = "",
    target_currency: str = "USD",
    email: str = "",
):
    return await asyncio.to_thread(
        engine.run_pipeline,
        str(file_path),
        user_location,
        target_currency,
        email,
    )


app = FastAPI(title="BOM Intelligence Engine", version="3.0.0")

# M-4: Restrict CORS to Platform API internal origins only.
# This engine is an internal microservice — not directly called by browsers.
_engine_cors_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_engine_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": "BOM Intelligence Engine",
        "version": "3.0.0",
        "status": "ok",
        "capabilities": ["parse", "normalize", "classify", "extract_specs"],
        "contracts": {
            "multipart_upload": "/api/analyze-bom",
            "internal_path_input": "/api/analyze-bom-path",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.now().isoformat()}


@app.post("/api/analyze-bom", dependencies=[Depends(verify_internal_key)])
async def analyze_bom(
    file: UploadFile = File(...),
    user_location: str = Form(""),
    target_currency: str = Form("USD"),
    email: str = Form(""),
):
    file_path = None
    try:
        file_path = _persist_upload(file)
        return await _run_pipeline_async(file_path, user_location, target_currency, email)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ENGINE_FAILED",
                "message": str(e),
            },
        )
    finally:
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass


@app.post("/api/analyze-bom-path", dependencies=[Depends(verify_internal_key)])
async def analyze_bom_path(
    file_path: str = Form(...),
    user_location: str = Form(""),
    target_currency: str = Form("USD"),
    email: str = Form(""),
):
    resolved_path = _resolve_input_path(file_path)
    try:
        return await _run_pipeline_async(resolved_path, user_location, target_currency, email)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ENGINE_FAILED",
                "message": str(e),
            },
        )