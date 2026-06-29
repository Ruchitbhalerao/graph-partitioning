from fastapi import Depends, HTTPException, Header
from typing import Optional
from ..services.optimization_service import OptimizationService
from ..services.upload_service import UploadService
from ..services.analytics_service import AnalyticsService
from ..services.export_service import ExportService


_optimization_service: Optional[OptimizationService] = None
_upload_service: Optional[UploadService] = None
_analytics_service: Optional[AnalyticsService] = None
_export_service: Optional[ExportService] = None


def get_optimization_service() -> OptimizationService:
    global _optimization_service
    if _optimization_service is None:
        _optimization_service = OptimizationService()
    return _optimization_service


def get_upload_service() -> UploadService:
    global _upload_service
    if _upload_service is None:
        _upload_service = UploadService()
    return _upload_service


def get_analytics_service() -> AnalyticsService:
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service


def get_export_service() -> ExportService:
    global _export_service
    if _export_service is None:
        _export_service = ExportService()
    return _export_service
