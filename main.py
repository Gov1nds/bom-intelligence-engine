"""BOM Intelligence Engine — FastAPI service."""
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "").strip()
UPLOAD_DIR = Path(os.getenv("BOM_ENGINE_UPLOAD_DIR", "uploads")).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = BOMIntelligenceEngine()


def verify_internal_key(x_internal_key: str = Header(default="")):
    if INTERNAL_API_KEY and x_internal_key.strip() != INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


app = FastAPI(title="BOM Intelligence Engine", version="4.0.0")

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    return {"service": "BOM Intelligence Engine", "version": "4.0.0", "status": "ok"}


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
    file_name = (file.filename or f"bom_{uuid.uuid4().hex}.bin").replace("/", "_").replace("\\", "_")
    file_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file_name}"

    with file_path.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)

    try:
        result = await asyncio.to_thread(engine.run_pipeline, str(file_path), user_location, target_currency, email)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error_code": "ENGINE_FAILED", "message": str(e)})
    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
