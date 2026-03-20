"""
BOM Intelligence Engine — Global Configuration
APIs, RL hyperparameters, regions, memory paths, feature flags.
"""
import os
from pathlib import Path
from functools import lru_cache

ENV = os.getenv("APP_ENV", "development")
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = PROJECT_ROOT / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

class BaseConfig:
    APP_NAME = "BOM Intelligence Engine"
    VERSION = "2.0.0"
    DEBUG = ENV == "development"

class DatabaseConfig:
    SQLITE_PATH = str(DATA_DIR / "bom_intelligence.db")

class DistributorAPIConfig:
    DIGIKEY_CLIENT_ID = os.getenv("DIGIKEY_CLIENT_ID", "")
    MOUSER_API_KEY = os.getenv("MOUSER_API_KEY", "")
    OCTOPART_API_KEY = os.getenv("OCTOPART_API_KEY", "")
    MISUMI_API_KEY = os.getenv("MISUMI_API_KEY", "")
    ARROW_API_KEY = os.getenv("ARROW_API_KEY", "")

class MarketDataConfig:
    LME_API_KEY = os.getenv("LME_API_KEY", "")
    FASTMARKETS_API_KEY = os.getenv("FASTMARKETS_API_KEY", "")

class LogisticsAPIConfig:
    FLEXPORT_API_KEY = os.getenv("FLEXPORT_API_KEY", "")

class ForexConfig:
    FX_API_KEY = os.getenv("FX_API_KEY", "")
    FX_VOLATILITY_BUFFER_PCT = 0.02

class RLConfig:
    GLOBAL_EXPLORATION_RATE = 0.15
    MIN_EXPLORATION_RATE = 0.03
    MAX_EXPLORATION_RATE = 0.40
    UCB_EXPLORATION_COEFFICIENT = 1.414
    UCB_RISK_PENALTY_WEIGHT = 0.20
    THOMPSON_SAMPLING_THRESHOLD = 5
    THOMPSON_PRIOR_ALPHA = 1.0
    THOMPSON_PRIOR_BETA = 1.0
    CONFIDENCE_DECAY_RATE = 0.01
    REGRET_GROWTH_RATE = 0.02
    COST_WEIGHT = 0.40
    LEADTIME_WEIGHT = 0.25
    RELIABILITY_WEIGHT = 0.20
    VARIANCE_WEIGHT = 0.15
    TIME_PENALTY_PER_DAY = 0.005

class MemoryConfig:
    PRICING_MEMORY_FILE = str(MEMORY_DIR / "pricing_memory.json")
    SUPPLIER_MEMORY_FILE = str(MEMORY_DIR / "supplier_memory.json")
    DECISION_MEMORY_FILE = str(MEMORY_DIR / "decision_memory.json")
    EXECUTION_TRACKING_FILE = str(MEMORY_DIR / "execution_tracking.json")
    PRICING_LEARNING_RATE = 0.1
    SUPPLIER_LEARNING_RATE = 0.15
    COST_BUFFER_DEFAULT = 0.10
    TIME_BUFFER_DEFAULT_DAYS = 3

class RegionConfig:
    """Dynamic region registry — expandable without code changes."""
    REGIONS = [
        {"id": "local", "label": "Local", "dynamic": True, "currency": "USD"},
        {"id": "CN", "label": "China", "country": "China", "currency": "CNY"},
        {"id": "IN", "label": "India", "country": "India", "currency": "INR"},
        {"id": "VN", "label": "Vietnam", "country": "Vietnam", "currency": "VND"},
        {"id": "EU", "label": "EU", "country": "Germany", "currency": "EUR"},
        {"id": "US", "label": "USA", "country": "USA", "currency": "USD"},
        {"id": "JP", "label": "Japan", "country": "Japan", "currency": "JPY"},
        {"id": "KR", "label": "South Korea", "country": "South Korea", "currency": "KRW"},
        {"id": "TW", "label": "Taiwan", "country": "Taiwan", "currency": "TWD"},
        {"id": "TH", "label": "Thailand", "country": "Thailand", "currency": "THB"},
        {"id": "MX", "label": "Mexico", "country": "Mexico", "currency": "MXN"},
    ]
    RISK = {"US":0.10,"EU":0.15,"JP":0.12,"KR":0.15,"TW":0.30,"CN":0.40,"IN":0.35,"VN":0.38,"TH":0.32,"MX":0.28,"local":0.10}
    COST_MULT = {"US":1.00,"EU":0.95,"JP":1.05,"KR":0.80,"TW":0.65,"CN":0.35,"IN":0.30,"VN":0.32,"TH":0.33,"MX":0.50,"local":1.00}
    LEAD_DAYS = {"US":5,"EU":18,"JP":16,"KR":17,"TW":18,"CN":25,"IN":22,"VN":24,"TH":23,"MX":10,"local":5}
    TARIFF = {"CN":0.08,"IN":0.05,"VN":0.04,"EU":0.03,"US":0.0,"JP":0.02,"KR":0.02,"TW":0.03,"TH":0.04,"MX":0.02,"local":0.0}
