"""Integration tests for OptimizationEngine — end-to-end pipeline."""

import pytest
import threading

from app.models.enums import OptimizationPhase
from app.models.progress import OptimizationProgressEvent
from app.optimization.engine import OptimizationEngine
from app.models.schemas import FTCRecord, FTCRelationshipRecord
from app.models.enums import ProductGroup


class TestOptimizationEngine:
    def test_initialization(self, engine):
        assert engine.config is not None
        assert engine.config.proximity_km > 0
        assert engine._timing == []

    def test_sm_region_pipeline(self, engine, mixed_dealers, mixed_ftcs):
        """End-to-end: run optimization on SM001 and verify results."""
        from app.data.processor import DataProcessor
        processor = DataProcessor()
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        rels = [
            FTCRelationshipRecord(
                Dealer_id=d.Dealer_id, FTC_id=f.FTC_id,
                Product_category=ProductGroup.PRODUCT_A,
            )
            for d in sm1_dealers[:2] for f in sm1_ftcs[:1]
        ]

        result = engine.run(sm1_dealers, sm1_ftcs, rels)

        assert "results" in result
        assert "status" in result
        assert "summary" in result
        assert result["status"] == "completed"

    def test_empty_input(self, engine):
        result = engine.run([], [], [])
        assert result["status"] == "completed"
        assert result["results"] == {}

    def test_only_static_dealers(self, engine, mixed_dealers, mixed_ftcs):
        """Engine should handle all-static case."""
        static = [d for d in mixed_dealers if d.SM_id == "SM002"]  # 1 static + mobiles
        sm2_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM002"]
        result = engine.run(static, sm2_ftcs, [])
        assert result["status"] == "completed"

    def test_progress_callback(self, engine, mixed_dealers, mixed_ftcs):
        """Verify progress callback is invoked during optimization."""
        events = []
        def cb(event):
            events.append(event)

        engine.set_progress_callback(cb)
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        engine.run(sm1_dealers, sm1_ftcs, [])

        assert len(events) > 0
        assert all(isinstance(e, OptimizationProgressEvent) for e in events)

    def test_cancellation(self, engine):
        """Cancellation should stop processing early."""
        cancel_event = threading.Event()
        engine.set_cancel_event(cancel_event)
        # Trigger cancellation immediately
        cancel_event.set()
        result = engine.run(
            [make_dealer("A", lat=19.0, lng=73.0)],
            [FTCRecord(FTC_id="FTC_1", SM_id="SM001", Product_Group=ProductGroup.PRODUCT_A, Average_cases_per_day=10.0)],
            [],
        )
        assert result["status"] in ("cancelled", "completed")

    def test_result_summary(self, engine, mixed_dealers, mixed_ftcs):
        """Verify summary contains expected metrics."""
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        result = engine.run(sm1_dealers, sm1_ftcs, [])

        summary = result.get("summary", {})
        assert summary["total_dealers"] == len(sm1_dealers)
        assert summary["total_ftcs"] == len(sm1_ftcs)
        assert "total_sm_regions" in summary
        assert "valid_regions" in summary

    def test_cross_sm_prevention(self, engine, mixed_dealers, mixed_ftcs):
        """Dealers from SM002 should not be assigned to FTCs from SM001."""
        result = engine.run(mixed_dealers, mixed_ftcs, [])
        for sm_id, sm_result in result.get("results", {}).items():
            for ftc_id in sm_result.get("assignments", {}):
                ftc = next((f for f in mixed_ftcs if f.FTC_id == ftc_id), None)
                if ftc:
                    assert ftc.SM_id == sm_id

    def test_phase_timing(self, engine, mixed_dealers, mixed_ftcs):
        """Phase timestamps should be recorded."""
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        result = engine.run(sm1_dealers, sm1_ftcs, [])

        timing = result.get("timing", [])
        assert len(timing) > 0
        phases = {t["phase"] for t in timing}
        assert "initial_territories" in phases

    def test_sm_progress_tracked(self, engine, mixed_dealers, mixed_ftcs):
        """SM-level progress dict should be populated."""
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        result = engine.run(sm1_dealers, sm1_ftcs, [])

        sm_progress = result.get("sm_progress", {})
        assert len(sm_progress) > 0
        for sm_id, progress in sm_progress.items():
            assert "sm_id" in progress
            assert "status" in progress
            assert "partners_count" in progress or "dealers_count" in progress

    def test_multiple_sm_regions(self, engine, mixed_dealers, mixed_ftcs):
        """Engine should handle multiple SM regions."""
        result = engine.run(mixed_dealers, mixed_ftcs, [])
        results = result.get("results", {})
        assert len(results) == 2  # SM001 and SM002
        assert all(sm_id in results for sm_id in ("SM001", "SM002"))

    def test_large_dataset(self, engine, many_dealers, many_ftcs):
        """Scale test with 500 dealers, 100 FTCs across 5 SM regions."""
        result = engine.run(many_dealers, many_ftcs, [])
        assert result["status"] == "completed"
        summary = result.get("summary", {})
        assert summary["total_dealers"] == len(many_dealers)
        assert summary["total_ftcs"] == len(many_ftcs)


# Helper for engine tests
from helpers import make_dealer
