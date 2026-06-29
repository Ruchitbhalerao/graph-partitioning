from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .config import settings
from .api.routes import router as api_router
from .monitoring.dashboard import router as monitoring_router
from .monitoring.logging_config import setup_logging, LogBuffer
from .monitoring.resource import get_resource_monitor, get_temp_file_manager
import os
import atexit

# Setup structured logging
_log_buffer = LogBuffer(max_entries=1000)
setup_logging(
    level=settings.LOG_LEVEL,
    json_format=settings.LOG_JSON_FORMAT,
    log_buffer=_log_buffer,
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(monitoring_router)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# Start resource monitoring
if settings.MONITORING_ENABLED:
    monitor = get_resource_monitor()
    monitor.start()


@app.on_event("startup")
async def startup():
    # Clean up old temp files on startup
    temp_mgr = get_temp_file_manager()
    temp_mgr.cleanup_expired()


@app.on_event("shutdown")
async def shutdown():
    if settings.MONITORING_ENABLED:
        get_resource_monitor().stop()
    get_temp_file_manager().cleanup_all()


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
