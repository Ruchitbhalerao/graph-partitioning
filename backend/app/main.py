from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from .config import settings
from .api.routes import bp as api_bp
from .monitoring.dashboard import bp as monitoring_bp
from .monitoring.logging_config import setup_logging, LogBuffer
from .monitoring.resource import get_resource_monitor, get_temp_file_manager
import os
import atexit


def create_app(testing=False):
    app = Flask(__name__, static_folder=None)

    app.config.from_object(settings)
    app.config["TESTING"] = testing

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Setup structured logging
    _log_buffer = LogBuffer(max_entries=1000)
    setup_logging(
        level=settings.LOG_LEVEL,
        json_format=settings.LOG_JSON_FORMAT,
        log_buffer=_log_buffer,
    )

    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(monitoring_bp, url_prefix="/monitoring")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

    # Start resource monitoring
    if settings.MONITORING_ENABLED:
        monitor = get_resource_monitor()
        monitor.start()

    # Clean up old temp files on startup
    temp_mgr = get_temp_file_manager()
    temp_mgr.cleanup_expired()

    # Serve frontend
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")
    if os.path.exists(frontend_dir):
        @app.route("/assets/<path:filename>")
        def frontend_assets(filename):
            return send_from_directory(os.path.join(frontend_dir, "assets"), filename)

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def frontend(path):
            if path and path.startswith(("api/", "monitoring/")):
                from flask import abort
                return abort(404)
            return send_from_directory(frontend_dir, "index.html")

    @app.route("/health")
    def health_check():
        return jsonify({
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        })

    # Register cleanup on shutdown
    def shutdown():
        if settings.MONITORING_ENABLED:
            get_resource_monitor().stop()
        get_temp_file_manager().cleanup_all()

    atexit.register(shutdown)

    return app
