import json
import traceback
from app.services.upload_service import UploadService
from app.services.optimization_service import OptimizationService
from app.optimization.engine import OptimizationEngine
from app.models.schemas import OptimizationConfig
from app.geography.qgis_exporter import QGISExporter
import os

with open("../Pune_Dataset_Large.xlsx", "rb") as f:
    content = f.read()

upload_service = UploadService()
result = upload_service.process_upload(content, "Pune_Dataset_Large.xlsx")

if result.status == "validated":
    upload_job = upload_service.get_job(result.job_id)
    dealers = upload_job.get("dealers", [])
    ftcs = upload_job.get("ftcs", [])
    rels = upload_job.get("rels", [])
    
    engine = OptimizationEngine(OptimizationConfig())
    opt_result = engine.run(dealers, ftcs, rels)
    
    print("Optimization finished.")
    
    exporter = QGISExporter(output_dir="/tmp/outputs")
    try:
        export_files = exporter.export_all(
            "test_job", opt_result.get("results", {}), dealers, ftcs,
            include_routes=False,
            style_info={"config": {}},
        )
        print("Export successful!")
    except Exception as e:
        print("Export error!")
        traceback.print_exc()
else:
    print("Validation failed.")
