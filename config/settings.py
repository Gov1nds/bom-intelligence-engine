"""BOM Intelligence Engine — Minimal Configuration (v3)."""
import os
from pathlib import Path

ENV = os.getenv("APP_ENV", "development")
PROJECT_ROOT = Path(__file__).parent.parent

class BaseConfig:
    APP_NAME = "BOM Intelligence Engine"
    VERSION = "3.0.0"
    DEBUG = ENV == "development"