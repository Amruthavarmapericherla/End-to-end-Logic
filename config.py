from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import timedelta

@dataclass(frozen=True)
class Config:
    # API
    API_URL: str = os.getenv("API_URL", "https://www.telekom.sk/delegate/getOfferFix")
    API_TIMEOUT_SEC: int = int(os.getenv("API_TIMEOUT_SEC", "15"))
    API_SOURCE: str = os.getenv("API_SOURCE", "web_b2b")
    API_MODE: str = os.getenv("API_MODE", "extended")
    API_SCENARIO: str = os.getenv("API_SCENARIO", "landing_page")

    # Mode (commitment window vs annual refresh)
    SCRAPER_MODE: str = os.getenv("SCRAPER_MODE", "COMMITMENT_WINDOW").upper()
    MIX_WINDOW_LIMIT_PER_CYCLE: int = int(os.getenv("MIX_WINDOW_LIMIT_PER_CYCLE", "50"))
    MIX_ANNUAL_LIMIT_PER_CYCLE: int = int(os.getenv("MIX_ANNUAL_LIMIT_PER_CYCLE", "100"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON: bool = os.getenv("LOG_JSON", "1") == "1"

    # Mongo
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://10.100.0.98:27017")
    MONGO_DB: str = os.getenv("MONGO_DB", "opt")
    MONGO_COLLECTION: str = os.getenv("MONGO_COLLECTION", "service")
    MONGO_ARCHIVE_COLLECTION: str = os.getenv("MONGO_ARCHIVE_COLLECTION", "service_archive")
    

    # MySQL (SQLAlchemy URL)
    MYSQL_URL: str = os.getenv("MYSQL_URL", "mysql+pymysql://rw-user:Ep5O2XJ9%5B26f@10.100.0.98:3306/marketing")
    MYSQL_TABLE: str = os.getenv("MYSQL_TABLE", "services_info")

    # Runner / pacing
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    INITIAL_BACKOFF_SEC: float = float(os.getenv("INITIAL_BACKOFF_SEC", "2.0"))
    BACKOFF_FACTOR: float = float(os.getenv("BACKOFF_FACTOR", "2.0"))
    JITTER_RANGE_SEC: float = float(os.getenv("JITTER_RANGE_SEC", "1.5"))
    TARGET_CYCLE_SEC: int = int(
        os.getenv("TARGET_CYCLE_SEC", str(int(timedelta(hours=1).total_seconds())))
    )

    # Processing controls
    BATCH_LIMIT: int = int(os.getenv("BATCH_LIMIT", "200"))
    PROCESS_DELAY_SEC: float = float(os.getenv("PROCESS_DELAY_SEC", "0"))

    # Schema knobs
    NUMBERS_FIELD: str = os.getenv("NUMBERS_FIELD", "numbers_info")
    NUMBER_KEY: str = os.getenv("NUMBER_KEY", "serviceId")

    # Archive length cap
    ARCHIVE_SNIPPET_LEN: int = int(os.getenv("ARCHIVE_SNIPPET_LEN", "10000"))

CONFIG = Config()

# --- Backwards-compat aliases (optional but helpful) ---
API_URL = CONFIG.API_URL
API_TIMEOUT_SEC = CONFIG.API_TIMEOUT_SEC
API_SOURCE = CONFIG.API_SOURCE
API_MODE = CONFIG.API_MODE
API_SCENARIO = CONFIG.API_SCENARIO

LOG_LEVEL = CONFIG.LOG_LEVEL
LOG_JSON = CONFIG.LOG_JSON

MONGO_URI = CONFIG.MONGO_URI
MONGO_DB = CONFIG.MONGO_DB
MONGO_COLLECTION = CONFIG.MONGO_COLLECTION
MONGO_ARCHIVE_COLLECTION = CONFIG.MONGO_ARCHIVE_COLLECTION


MYSQL_URL = CONFIG.MYSQL_URL
MYSQL_TABLE = CONFIG.MYSQL_TABLE

MAX_RETRIES = CONFIG.MAX_RETRIES
INITIAL_BACKOFF_SEC = CONFIG.INITIAL_BACKOFF_SEC
BACKOFF_FACTOR = CONFIG.BACKOFF_FACTOR
JITTER_RANGE_SEC = CONFIG.JITTER_RANGE_SEC
TARGET_CYCLE_SEC = CONFIG.TARGET_CYCLE_SEC

BATCH_LIMIT = CONFIG.BATCH_LIMIT
PROCESS_DELAY_SEC = CONFIG.PROCESS_DELAY_SEC

NUMBERS_FIELD = CONFIG.NUMBERS_FIELD
NUMBER_KEY = CONFIG.NUMBER_KEY

ARCHIVE_SNIPPET_LEN = CONFIG.ARCHIVE_SNIPPET_LEN

# Modes
SCRAPER_MODE = CONFIG.SCRAPER_MODE
MIX_WINDOW_LIMIT_PER_CYCLE = CONFIG.MIX_WINDOW_LIMIT_PER_CYCLE
MIX_ANNUAL_LIMIT_PER_CYCLE = CONFIG.MIX_ANNUAL_LIMIT_PER_CYCLE
