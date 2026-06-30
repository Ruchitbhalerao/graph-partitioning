from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    APP_NAME: str = "Territory Optimization System"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: List[str] = [".xlsx", ".xls", ".csv"]

    DEFAULT_PROXIMITY_KM: float = 5.0
    DEFAULT_TRAVEL_WEIGHT: float = 0.35
    DEFAULT_WORKLOAD_WEIGHT: float = 0.30
    DEFAULT_COMPACTNESS_WEIGHT: float = 0.20
    DEFAULT_PRODUCTIVITY_WEIGHT: float = 0.15

    MAX_REFINEMENT_ITERATIONS: int = 100
    TABU_TENURE: int = 10
    REFINEMENT_NEIGHBORHOOD_SIZE: int = 20

    CRS_EPSG: int = 4326
    OUTPUT_CRS: str = "EPSG:4326"

    H3_RESOLUTION: int = 8

    DB_HOST: Optional[str] = None
    DB_PORT: int = 5432
    DB_NAME: Optional[str] = None
    DB_USER: Optional[str] = None
    DB_PASS: Optional[str] = None

    UPLOAD_DIR: str = "/tmp/uploads"
    OUTPUT_DIR: str = "/tmp/outputs"
    UPLOAD_CLEANUP_HOURS: int = 24

    # Monitoring settings
    MONITORING_ENABLED: bool = True
    METRICS_INTERVAL_SEC: float = 30.0
    LOG_LEVEL: str = "INFO"
    LOG_JSON_FORMAT: bool = True

    # Performance settings
    PARALLEL_SM_PROCESSING: bool = True
    MAX_CONCURRENT_SM: int = 4
    ENABLE_GRAPH_CACHE: bool = True
    ENABLE_POLYGON_CACHE: bool = True

    # Resource management
    TEMP_FILE_MAX_AGE_HOURS: int = 24
    MAX_MEMORY_MB: int = 2048
    DEFAULT_TIMEOUT_SEC: int = 600
    MAX_RETRIES: int = 3

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
