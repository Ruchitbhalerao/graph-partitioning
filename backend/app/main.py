from flask import Flask, jsonify, send_from_directory, Response
from flask_cors import CORS
from .config import settings
from .api.routes import bp as api_bp
from .monitoring.dashboard import bp as monitoring_bp
from .monitoring.logging_config import setup_logging, LogBuffer
from .monitoring.resource import get_resource_monitor, get_temp_file_manager
import os
import re
import atexit


# Script injected into the page to add the "Open Map" button
_MAP_BUTTON_SCRIPT = """
<script>
(function(){
  var _jid=null;
  function getJobId(){
    if(_jid)return _jid;
    var all=document.body.innerText||'';
    var m=all.match(/Job:\\s*([a-f0-9]{8})/i);
    if(m){_jid=m[1];return _jid;}
    return null;
  }
  function resetJobId(){_jid=null;}
  function inject(){
    if(document.getElementById('open-map-btn'))return;
    var wrap=document.createElement('div');
    wrap.id='open-map-btn-wrap';
    wrap.style.cssText='position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;gap:8px;align-items:center;';
    var btn=document.createElement('button');
    btn.id='open-map-btn';
    btn.textContent='Open Map';
    btn.style.cssText='padding:10px 20px;border:none;border-radius:8px;background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,0.3);transition:opacity 0.2s;';
    btn.onmouseenter=function(){btn.style.opacity='0.85';};
    btn.onmouseleave=function(){btn.style.opacity='1';};
    btn.onclick=function(){
      var jid=getJobId();
      if(jid){window.open('/api/v1/map/'+jid,'_blank');}
      else{alert('No active job. Upload data first.');}
    };
    wrap.appendChild(btn);
    document.body.appendChild(wrap);
  }
  function check(){
    var jid=getJobId();
    var btn=document.getElementById('open-map-btn');
    if(btn){btn.style.display='block';}
  }
  inject();
  check();
  setInterval(check,2000);
  window._resetMapJobId=resetJobId;
})();
</script>
"""


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
        _index_html_cache = None

        def _read_index_html():
            nonlocal _index_html_cache
            if _index_html_cache is None:
                with open(os.path.join(frontend_dir, "index.html"), "r") as f:
                    content = f.read()
                # Inject the map button script before </body>
                if _MAP_BUTTON_SCRIPT.strip() not in content:
                    content = content.replace("</body>", _MAP_BUTTON_SCRIPT + "\n</body>")
                _index_html_cache = content
            return _index_html_cache

        @app.route("/assets/<path:filename>")
        def frontend_assets(filename):
            return send_from_directory(os.path.join(frontend_dir, "assets"), filename)

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def frontend(path):
            if path and path.startswith(("api/", "monitoring/")):
                from flask import abort
                return abort(404)
            return Response(_read_index_html(), mimetype="text/html")

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
