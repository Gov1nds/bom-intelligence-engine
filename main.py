"""BOM Intelligence Engine — FastAPI service (v5.0.0).

Endpoints:
  POST /api/normalize   — per-line normalization (new)
  POST /api/enrich      — per-line enrichment (new)
  POST /api/score       — per-line scoring (new)
  POST /api/strategy    — per-line strategy (new)
  POST /api/analyze-bom — legacy file-upload (retained)
  GET  /readiness       — readiness probe
  GET  /liveness        — liveness probe
  GET  /startup         — startup probe
"""
import asyncio
import logging
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent))

from core.config import config
from core.schemas import (
    SCHEMA_VERSION, ErrorEnvelope,
    NormalizationRequest, NormalizationResponse,
    EnrichmentRequest, EnrichmentResponse,
    ScoringRequest, ScoringResponse,
    StrategyRequest, StrategyResponse,
)
from engine.orchestrator import BOMIntelligenceEngine
from engine.observability import configure_observability

logger = logging.getLogger("main")

# ── Fail-fast production validation ──
config.validate_production()

# ── Application ──
app = FastAPI(title="BOM Intelligence Engine", version=SCHEMA_VERSION)

# Structured logging + optional OpenTelemetry
configure_observability(app=app, config=config)

# CORS
origins = [o.strip() for o in config.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

UPLOAD_DIR = Path(config.BOM_ENGINE_UPLOAD_DIR).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = set(config.ALLOWED_FILE_EXTENSIONS.split(","))

engine = BOMIntelligenceEngine()


# ── Auth ──

def verify_internal_key(x_internal_key: str = Header(default="")) -> None:
    if config.INTERNAL_API_KEY and x_internal_key.strip() != config.INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def get_trace_id(x_trace_id: str = Header(default="")) -> str:
    return x_trace_id.strip() or str(uuid.uuid4())


# ── Error handler ──

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = request.headers.get("x-trace-id", "")
    envelope = ErrorEnvelope(
        error_code="INTERNAL_ERROR",
        message=str(exc),
        trace_id=trace_id,
    )
    return JSONResponse(status_code=500, content=envelope.model_dump())


# ── Health probes ──

@app.get("/")
def root():
    return {"service": "BOM Intelligence Engine", "version": SCHEMA_VERSION, "status": "ok"}


@app.get("/readiness")
def readiness():
    return {"status": "ok", "ts": datetime.now().isoformat(), "version": SCHEMA_VERSION}


@app.get("/liveness")
def liveness():
    return {"status": "ok"}


@app.get("/startup")
def startup():
    return {"status": "ok", "version": SCHEMA_VERSION}


# ── Decomposed endpoints (new) ──

@app.post("/api/normalize", response_model=NormalizationResponse)
async def normalize(
    request: NormalizationRequest,
    _key: None = Depends(verify_internal_key),
    trace_id: str = Depends(get_trace_id),
):
    try:
        result = await asyncio.to_thread(engine.normalize, request)
        return result
    except Exception as e:
        logger.exception("Normalization failed")
        raise HTTPException(status_code=500, detail={
            "error_code": "NORMALIZATION_FAILED", "message": str(e), "trace_id": trace_id
        })


@app.post("/api/enrich", response_model=EnrichmentResponse)
async def enrich(
    request: EnrichmentRequest,
    _key: None = Depends(verify_internal_key),
    trace_id: str = Depends(get_trace_id),
):
    try:
        result = await asyncio.to_thread(engine.enrich, request)
        return result
    except Exception as e:
        logger.exception("Enrichment failed")
        raise HTTPException(status_code=500, detail={
            "error_code": "ENRICHMENT_FAILED", "message": str(e), "trace_id": trace_id
        })


@app.post("/api/score", response_model=ScoringResponse)
async def score(
    request: ScoringRequest,
    _key: None = Depends(verify_internal_key),
    trace_id: str = Depends(get_trace_id),
):
    try:
        result = await asyncio.to_thread(engine.score, request)
        return result
    except Exception as e:
        logger.exception("Scoring failed")
        raise HTTPException(status_code=500, detail={
            "error_code": "SCORING_FAILED", "message": str(e), "trace_id": trace_id
        })


@app.post("/api/strategy", response_model=StrategyResponse)
async def strategy(
    request: StrategyRequest,
    _key: None = Depends(verify_internal_key),
    trace_id: str = Depends(get_trace_id),
):
    try:
        result = await asyncio.to_thread(engine.strategy, request)
        return result
    except Exception as e:
        logger.exception("Strategy failed")
        raise HTTPException(status_code=500, detail={
            "error_code": "STRATEGY_FAILED", "message": str(e), "trace_id": trace_id
        })


# ── Legacy endpoint ──

@app.post("/api/analyze-bom", dependencies=[Depends(verify_internal_key)])
async def analyze_bom(
    file: UploadFile = File(...),
    user_location: str = Form(""),
    target_currency: str = Form("USD"),
    email: str = Form(""),
    trace_id: str = Depends(get_trace_id),
):
    # File type validation
    file_name = (file.filename or f"bom_{uuid.uuid4().hex}.bin").replace("/", "_").replace("\\", "_")
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail={
            "error_code": "UNSUPPORTED_FILE_TYPE",
            "message": f"File type '{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            "trace_id": trace_id,
        })

    file_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file_name}"

    # File size validation (stream check)
    with file_path.open("wb") as buf:
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > config.MAX_UPLOAD_SIZE_BYTES:
                file_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail={
                    "error_code": "FILE_TOO_LARGE",
                    "message": f"File exceeds {config.MAX_UPLOAD_SIZE_BYTES} bytes",
                    "trace_id": trace_id,
                })
            buf.write(chunk)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                engine.run_pipeline, str(file_path), user_location, target_currency, email
            ),
            timeout=config.ANALYSIS_TIMEOUT_SECONDS,
        )
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail={
            "error_code": "ANALYSIS_TIMEOUT",
            "message": f"Analysis exceeded {config.ANALYSIS_TIMEOUT_SECONDS}s timeout",
            "trace_id": trace_id,
        })
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail={
            "error_code": "ENGINE_FAILED", "message": str(e), "trace_id": trace_id
        })
    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
