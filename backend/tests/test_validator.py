"""Unit tests for BusinessRuleValidator and DataValidator."""

import pytest
import networkx as nx

from app.optimization.validator import BusinessRuleValidator
from app.data.validator import DataValidator
from app.models.enums import DealerType, ProductGroup
from app.models.schemas import DealerRecord, FTCRecord, FTCRelationshipRecord
from helpers import make_dealer, make_ftc, make_relationship


class TestBusinessRuleValidator:
    def test_no_errors_valid(self, simple_dealers, simple_ftcs, simple_graph):
        validator = BusinessRuleValidator()
        assignments = {"FTC_1": ["DLR_A", "DLR_B"], "FTC_2": ["DLR_C"]}
        is_valid, errors = validator.validate_all(assignments, simple_dealers, simple_ftcs, simple_graph)
        assert is_valid
        assert len(errors) == 0

    def test_cross_sm_detected(self):
        validator = BusinessRuleValidator()
        dealers = [
            make_dealer("D1", sm_id="SM001"),
            make_dealer("D2", sm_id="SM002"),
        ]
        ftcs = [make_ftc("F1", sm_id="SM001")]
        G = nx.Graph()
        G.add_node("D1"), G.add_node("D2")
        G.add_edge("D1", "D2", weight=0.5)
        assignments = {"F1": ["D1", "D2"]}

        is_valid, errors = validator.validate_all(assignments, dealers, ftcs, G)
        assert not is_valid
        assert any("Cross-SM" in e for e in errors)

    def test_unassigned_static_dealer(self):
        validator = BusinessRuleValidator()
        dealers = [
            make_dealer("D1", dealer_type=DealerType.STATIC),
            make_dealer("D2", dealer_type=DealerType.MOBILE),
        ]
        ftcs = [make_ftc("F1")]
        G = nx.Graph()
        G.add_node("D1"), G.add_node("D2")
        G.add_edge("D1", "D2", weight=0.5)
        assignments = {"F1": ["D2"]}

        is_valid, errors = validator.validate_all(assignments, dealers, ftcs, G)
        assert not is_valid
        assert any("no FTC assignment" in e for e in errors)

    def test_overlapping_assignments(self):
        validator = BusinessRuleValidator()
        dealers = [make_dealer("D1")]
        ftcs = [make_ftc("F1"), make_ftc("F2")]
        G = nx.Graph()
        G.add_node("D1")
        assignments = {"F1": ["D1"], "F2": ["D1"]}

        is_valid, errors = validator.validate_all(assignments, dealers, ftcs, G)
        assert not is_valid
        assert any("assigned to both" in e for e in errors)

    def test_capacity_exceeded(self):
        validator = BusinessRuleValidator()
        dealers = [make_dealer("D1", cases=100.0)]
        ftcs = [make_ftc("F1", cases=10.0)]
        G = nx.Graph()
        G.add_node("D1")
        assignments = {"F1": ["D1"]}

        is_valid, errors = validator.validate_all(assignments, dealers, ftcs, G)
        assert not is_valid
        assert any("capacity" in e.lower() for e in errors)

    def test_disconnected_territory(self):
        validator = BusinessRuleValidator()
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D2", lat=28.6, lng=77.2),
        ]
        ftcs = [make_ftc("F1")]
        G = nx.Graph()
        G.add_node("D1"), G.add_node("D2")
        assignments = {"F1": ["D1", "D2"]}

        is_valid, errors = validator.validate_all(assignments, dealers, ftcs, G)
        assert not is_valid
        assert any("disconnected" in e for e in errors)

    def test_all_unassigned_dealer(self):
        validator = BusinessRuleValidator()
        dealers = [make_dealer("D1"), make_dealer("D2")]
        ftcs = [make_ftc("F1")]
        G = nx.Graph()
        G.add_node("D1"), G.add_node("D2")
        G.add_edge("D1", "D2", weight=0.5)
        assignments = {"F1": ["D1"]}

        is_valid, errors = validator.validate_all(assignments, dealers, ftcs, G)
        assert not is_valid
        assert any("unassigned" in e for e in errors)


class TestDataValidator:
    def test_validate_valid_dealers(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", lat=19.0, lng=73.0)]
        ftcs = [make_ftc("F1", sm_id="SM001")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert is_valid
        assert len(errors) == 0

    def test_invalid_latitude(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", lat=100.0, lng=73.0)]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("latitude" in e.lower() for e in errors)

    def test_invalid_longitude(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", lat=19.0, lng=200.0)]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("longitude" in e.lower() for e in errors)

    def test_duplicate_dealer_id(self):
        validator = DataValidator()
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D1", lat=19.1, lng=73.1),
        ]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("Duplicate" in e for e in errors)

    def test_duplicate_ftc_id(self):
        validator = DataValidator()
        dealers = [make_dealer("D1")]
        ftcs = [
            make_ftc("F1"),
            make_ftc("F1"),
        ]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("Duplicate" in e for e in errors)

    def test_negative_cases(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", cases=-5.0)]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("negative" in e.lower() for e in errors)

    def test_static_dealer_zero_cases(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", dealer_type=DealerType.STATIC, cases=0)]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("Static" in e for e in errors)

    def test_ntb_share_out_of_range(self):
        validator = DataValidator()
        dealers = [make_dealer("D1")]
        ftcs = [make_ftc("F1", ntb=1.5)]  # > 1.0
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("NTB_share" in e for e in errors)

    def test_relationship_dealer_not_found(self):
        validator = DataValidator()
        dealers = [make_dealer("D1")]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("UNKNOWN", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("not found" in e for e in errors)

    def test_relationship_ftc_not_found(self):
        validator = DataValidator()
        dealers = [make_dealer("D1")]
        ftcs = [make_ftc("F1")]
        rels = [make_relationship("D1", "UNKNOWN")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("not found" in e for e in errors)

    def test_cross_sm_relationship(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", sm_id="SM001")]
        ftcs = [make_ftc("F1", sm_id="SM002")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        assert any("Cross-SM" in e for e in errors)

    def test_sm_consistency_missing_ftc(self):
        validator = DataValidator()
        dealers = [make_dealer("D1", sm_id="SM001")]
        ftcs = [make_ftc("F1", sm_id="SM002")]
        rels = [make_relationship("D1", "F1")]
        is_valid, errors = validator.validate(dealers, ftcs, rels)
        assert not is_valid
        # Should warn about SM001 having dealers but no FTCs
        sm_errors = [e for e in errors if "no FTCs" in e]
        assert len(sm_errors) > 0

    def test_valid_coordinates(self):
        assert DataValidator._is_valid_lat(0)
        assert DataValidator._is_valid_lat(90)
        assert DataValidator._is_valid_lat(-90)
        assert not DataValidator._is_valid_lat(91)
        assert not DataValidator._is_valid_lat(-91)
        assert DataValidator._is_valid_lon(0)
        assert DataValidator._is_valid_lon(180)
        assert DataValidator._is_valid_lon(-180)
        assert not DataValidator._is_valid_lon(181)
