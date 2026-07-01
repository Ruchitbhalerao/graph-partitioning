import os
import json
import csv
import zipfile
import threading
import shutil
import time
from typing import Dict, Optional, List, Any, Set
from datetime import datetime, timedelta
from flask import send_file, Response
from ..config import settings
from ..models.schemas import DealerRecord, FTCRecord


EXPORT_MEDIA_TYPES = {
    ".geojson": "application/geo+json",
    ".csv": "text/csv",
    ".json": "application/json",
    ".zip": "application/zip",
    ".html": "text/html",
    ".qgs": "application/x-qgis-project",
    ".qml": "application/x-qgis-style",
}


class ExportJobManager:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self._locks: Dict[str, threading.Lock] = {}
        self._status: Dict[str, Dict] = {}
        self._completion_events: Dict[str, threading.Event] = {}

    def _lock(self, key: str) -> threading.Lock:
        if key not in self._locks:
            self._locks[key] = threading.Lock()
        return self._locks[key]

    def get_status(self, job_id: str) -> Optional[Dict]:
        return self._status.get(job_id)

    def set_status(self, job_id: str, status: Dict):
        with self._lock(job_id):
            self._status[job_id] = status

    def update_status(self, job_id: str, **kwargs):
        with self._lock(job_id):
            if job_id not in self._status:
                self._status[job_id] = {}
            self._status[job_id].update(kwargs)

    def get_job_dir(self, job_id: str) -> str:
        return os.path.join(self.output_dir, job_id)

    def cleanup_job(self, job_id: str):
        job_dir = self.get_job_dir(job_id)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
        with self._lock(job_id):
            self._status.pop(job_id, None)

    def cleanup_expired(self, max_age_hours: int = 24):
        cutoff = time.time() - (max_age_hours * 3600)
        for job_id in list(self._status.keys()):
            status = self._status.get(job_id, {})
            created = status.get("created_at", 0)
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created).timestamp()
                except (ValueError, TypeError):
                    created = 0
            if created > 0 and created < cutoff:
                self.cleanup_job(job_id)

    def estimate_file_sizes(self, results: Dict, dealers: List) -> Dict[str, str]:
        dealer_count = len(dealers) if dealers else 0
        ftc_count = sum(r.get("ftc_count", 0) for r in results.values())
        sm_count = len(results)

        def est(label: str, factor: float, unit: str = "KB"):
            size_kb = max(1, int(factor))
            if size_kb < 1024:
                return f"{size_kb} KB"
            return f"{size_kb / 1024:.1f} MB"

        return {
            "territories_geojson": est("Territories", dealer_count * 0.8),
            "dealers_geojson": est("Dealers", dealer_count * 0.3),
            "sm_boundaries_geojson": est("SM Boundaries", sm_count * 0.5),
            "routes_geojson": est("Routes", ftc_count * 0.4),
            "assignments_csv": est("Assignments", dealer_count * 0.05),
            "dealers_csv": est("Dealers CSV", dealer_count * 0.05),
            "sm_summary_csv": est("SM Summary", sm_count * 0.02),
            "shapefile_zip": est("Shapefile", dealer_count * 0.9),
            "metadata_json": est("Metadata", 5),
        }


class ExportValidator:
    @staticmethod
    def validate_geojson(filepath: str) -> Dict:
        errors = []
        warnings = []
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            if data.get("type") != "FeatureCollection":
                errors.append("Root type must be FeatureCollection")
            features = data.get("features", [])
            if not features:
                warnings.append("FeatureCollection is empty")
            for i, feat in enumerate(features):
                if feat.get("type") != "Feature":
                    errors.append(f"Feature {i}: type must be Feature")
                geom = feat.get("geometry", {})
                if not geom.get("type"):
                    errors.append(f"Feature {i}: missing geometry type")
                if not geom.get("coordinates"):
                    errors.append(f"Feature {i}: missing coordinates")
            return {
                "file": os.path.basename(filepath),
                "format": "GeoJSON",
                "valid": len(errors) == 0,
                "feature_count": len(features),
                "errors": errors,
                "warnings": warnings,
            }
        except json.JSONDecodeError as e:
            return {
                "file": os.path.basename(filepath),
                "format": "GeoJSON",
                "valid": False,
                "feature_count": 0,
                "errors": [f"Invalid JSON: {e}"],
                "warnings": [],
            }
        except Exception as e:
            return {
                "file": os.path.basename(filepath),
                "format": "GeoJSON",
                "valid": False,
                "feature_count": 0,
                "errors": [str(e)],
                "warnings": [],
            }

    @staticmethod
    def validate_csv(filepath: str) -> Dict:
        errors = []
        warnings = []
        row_count = 0
        columns = []
        try:
            with open(filepath, "r") as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                columns = headers
                if not headers:
                    errors.append("CSV has no headers")
                for i, row in enumerate(reader):
                    row_count += 1
                    if not row or all(c.strip() == "" for c in row):
                        warnings.append(f"Row {i + 2}: empty row")
                    elif len(row) != len(headers):
                        errors.append(
                            f"Row {i + 2}: expected {len(headers)} columns, got {len(row)}"
                        )
            return {
                "file": os.path.basename(filepath),
                "format": "CSV",
                "valid": len(errors) == 0,
                "row_count": row_count,
                "columns": columns,
                "errors": errors,
                "warnings": warnings,
            }
        except Exception as e:
            return {
                "file": os.path.basename(filepath),
                "format": "CSV",
                "valid": False,
                "row_count": 0,
                "columns": [],
                "errors": [str(e)],
                "warnings": [],
            }

    @staticmethod
    def validate_shapefile_zip(filepath: str) -> Dict:
        errors = []
        warnings = []
        file_list = []
        try:
            with zipfile.ZipFile(filepath, "r") as zf:
                names = zf.namelist()
                file_list = names
                shp_files = [n for n in names if n.endswith(".shp")]
                if not shp_files:
                    errors.append("No .shp files found in ZIP")
                shx_files = [n for n in names if n.endswith(".shx")]
                if not shx_files:
                    warnings.append("No .shx index files found")
                dbf_files = [n for n in names if n.endswith(".dbf")]
                if not dbf_files:
                    warnings.append("No .dbf attribute files found")
                prj_files = [n for n in names if n.endswith(".prj")]
                if not prj_files:
                    warnings.append("No .prj projection files found")
            return {
                "file": os.path.basename(filepath),
                "format": "Shapefile (ZIP)",
                "valid": len(errors) == 0,
                "file_count": len(names),
                "files": file_list,
                "errors": errors,
                "warnings": warnings,
            }
        except zipfile.BadZipFile:
            return {
                "file": os.path.basename(filepath),
                "format": "Shapefile (ZIP)",
                "valid": False,
                "file_count": 0,
                "files": [],
                "errors": ["Invalid ZIP file"],
                "warnings": [],
            }
        except Exception as e:
            return {
                "file": os.path.basename(filepath),
                "format": "Shapefile (ZIP)",
                "valid": False,
                "file_count": 0,
                "files": [],
                "errors": [str(e)],
                "warnings": [],
            }

    @staticmethod
    def validate_export_package(filepath: str) -> Dict:
        reports = {}

        if filepath.endswith(".geojson"):
            reports["geojson"] = ExportValidator.validate_geojson(filepath)
        elif filepath.endswith(".csv"):
            reports["csv"] = ExportValidator.validate_csv(filepath)
        elif filepath.endswith(".zip"):
            reports["shapefile"] = ExportValidator.validate_shapefile_zip(filepath)

        return reports


class ExportService:
    def __init__(self):
        self.job_manager = ExportJobManager(settings.OUTPUT_DIR)
        self.validator = ExportValidator()

    def get_export_file(
        self,
        export_files: Dict[str, str],
        file_type: str = "territories_geojson",
    ):
        filepath = export_files.get(file_type)
        if not filepath or not os.path.exists(filepath):
            return None

        ext = filepath.rsplit(".", 1)[-1] if "." in filepath else ""
        media_type = EXPORT_MEDIA_TYPES.get(f".{ext}", "application/octet-stream")

        return send_file(
            filepath,
            mimetype=media_type,
            as_attachment=True,
            download_name=os.path.basename(filepath),
        )

    def read_geojson(self, filepath: str) -> Optional[Dict]:
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r") as f:
            return json.load(f)

    def read_csv_as_dict(self, filepath: str) -> Optional[list]:
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def list_export_files(self, job_id: str) -> List[Dict]:
        job_dir = self.job_manager.get_job_dir(job_id)
        result = []
        if not os.path.exists(job_dir):
            return result
        for fname in sorted(os.listdir(job_dir)):
            fpath = os.path.join(job_dir, fname)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                result.append({
                    "filename": fname,
                    "size_bytes": size,
                    "size_label": self._format_size(size),
                    "type": fname.rsplit(".", 1)[-1] if "." in fname else "unknown",
                })
        return result

    def get_export_status(self, job_id: str) -> Optional[Dict]:
        status = self.job_manager.get_status(job_id)
        if status:
            files = self.list_export_files(job_id)
            status["files"] = files
            status["total_size"] = sum(f["size_bytes"] for f in files)
        return status

    def validate_exports(self, job_id: str) -> Dict:
        job_dir = self.job_manager.get_job_dir(job_id)
        results = {"job_id": job_id, "validated_at": datetime.now().isoformat(), "reports": []}
        if not os.path.exists(job_dir):
            results["error"] = "No exports found"
            return results

        for fname in sorted(os.listdir(job_dir)):
            fpath = os.path.join(job_dir, fname)
            if os.path.isfile(fpath) and fname != "manifest.json":
                if fname.endswith(".geojson"):
                    report = self.validator.validate_geojson(fpath)
                elif fname.endswith(".csv"):
                    report = self.validator.validate_csv(fpath)
                elif fname.endswith(".zip"):
                    report = self.validator.validate_shapefile_zip(fpath)
                else:
                    continue
                results["reports"].append(report)

        results["total_valid"] = sum(1 for r in results["reports"] if r.get("valid"))
        results["total_with_errors"] = sum(1 for r in results["reports"] if not r.get("valid"))
        results["all_valid"] = results["total_with_errors"] == 0
        return results

    def generate_bulk_export(
        self, job_ids: List[str], formats: List[str],
    ) -> Optional[Dict[str, str]]:
        bulk_id = f"bulk_{int(time.time())}"
        bulk_dir = os.path.join(settings.OUTPUT_DIR, bulk_id)
        os.makedirs(bulk_dir, exist_ok=True)

        included_files = []
        for job_id in job_ids:
            job_dir = self.job_manager.get_job_dir(job_id)
            if not os.path.exists(job_dir):
                continue
            for fname in os.listdir(job_dir):
                fpath = os.path.join(job_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
                if not formats or ext in formats or fname.endswith("_manifest.json"):
                    dest = os.path.join(bulk_dir, f"{job_id}_{fname}")
                    shutil.copy2(fpath, dest)
                    included_files.append(f"{job_id}_{fname}")

        if not included_files:
            shutil.rmtree(bulk_dir, ignore_errors=True)
            return None

        manifest = {
            "bulk_id": bulk_id,
            "generated_at": datetime.now().isoformat(),
            "job_ids": job_ids,
            "total_files": len(included_files),
            "files": included_files,
        }
        with open(os.path.join(bulk_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        return {"bulk_id": bulk_id, "bulk_dir": bulk_dir}

    def get_bulk_export_zip(self, bulk_dir: str):
        if not os.path.exists(bulk_dir):
            return None
        import tempfile
        zip_path = os.path.join(tempfile.gettempdir(), f"{os.path.basename(bulk_dir)}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(bulk_dir)):
                fpath = os.path.join(bulk_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=fname)

        return send_file(
            zip_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{os.path.basename(bulk_dir)}.zip",
        )

    def cleanup_old_exports(self, max_age_hours: int = 24):
        self.job_manager.cleanup_expired(max_age_hours)

    def cleanup_bulk_export(self, bulk_dir: str):
        if os.path.exists(bulk_dir):
            shutil.rmtree(bulk_dir, ignore_errors=True)
        zip_path = os.path.join(
            os.path.dirname(bulk_dir),
            f"{os.path.basename(bulk_dir)}.zip",
        )
        if os.path.exists(zip_path):
            os.remove(zip_path)

    @staticmethod
    def _format_size(bytes_: int) -> str:
        if bytes_ < 1024:
            return f"{bytes_} B"
        elif bytes_ < 1024 * 1024:
            return f"{bytes_ / 1024:.1f} KB"
        else:
            return f"{bytes_ / (1024 * 1024):.1f} MB"
