import json
from app.main import create_app
app = create_app()
from app.services.upload_service import UploadService
from app.services.optimization_service import OptimizationService
from app.optimization.engine import OptimizationEngine
from app.models.schemas import OptimizationConfig

with open("../Pune_Dataset_Large.xlsx", "rb") as f:
    content = f.read()

upload_service = UploadService()
result = upload_service.process_upload(content, "Pune_Dataset_Large.xlsx")

if result.status == "validated":
    upload_job = upload_service.get_job(result.job_id)
    dealers = upload_job.get("dealers", [])
    ftcs = upload_job.get("ftcs", [])
    rels = upload_job.get("rels", [])
    
    from app.api.dependencies import get_optimization_service
    opt_service = get_optimization_service()
    
    job_id = opt_service.start_optimization()
    opt_service.set_job_data(
        job_id=job_id,
        dealers=dealers,
        ftcs=ftcs,
        rels=rels,
        status="validated"
    )
    
    engine = OptimizationEngine(OptimizationConfig())
    opt_result = engine.run(dealers, ftcs, rels)
    
    opt_service.jobs[job_id]["result"] = opt_result
    opt_service.jobs[job_id]["status"] = "completed"
    
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/export/bulk",
            json={
                "job_ids": [job_id],
                "formats": ["geojson", "csv", "zip"]
            }
        )
        print("Bulk export status code:", resp.status_code)
        print("Bulk export response:", resp.get_json())
