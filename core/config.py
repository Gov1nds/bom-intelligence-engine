"""Centralized configuration per ops-config.yaml and GAP-032."""
from pydantic_settings import BaseSettings


class EngineConfig(BaseSettings):
    # Core
    PLATFORM_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    ENGINE_PORT: int = 8001
    ENGINE_VERSION: str = "5.0.0"

    # Auth
    INTERNAL_API_KEY: str = ""

    # File handling
    BOM_ENGINE_UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_BYTES: int = 52_428_800
    ALLOWED_FILE_EXTENSIONS: str = ".csv,.tsv,.xlsx,.xls,.txt"

    # Processing
    ANALYSIS_TIMEOUT_SECONDS: int = 120
    NORMALIZATION_TIMEOUT_MS: int = 500
    ENRICHMENT_TIMEOUT_MS: int = 1000
    SCORING_TIMEOUT_MS: int = 500
    MAX_BOM_ROWS: int = 5000

    # NLP / Model
    NLP_MODEL_PATH: str = ""
    PART_MASTER_INDEX_PATH: str = ""
    ABBREVIATION_DICT_PATH: str = ""

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "bom-intelligence-engine"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://localhost:3000"

    # Confidence thresholds (SM-001, PC-002)
    CONFIDENCE_AUTO_THRESHOLD: float = 0.85
    CONFIDENCE_REVIEW_REQUIRED_THRESHOLD: float = 0.50

    # ML feature output (WP-10)
    EMIT_ML_FEATURES: bool = False

    model_config = {"env_file": ".env", "case_sensitive": True}

    def validate_production(self) -> None:
        if self.PLATFORM_ENV == "production":
            assert self.INTERNAL_API_KEY, "INTERNAL_API_KEY must be set in production"


config = EngineConfig()
