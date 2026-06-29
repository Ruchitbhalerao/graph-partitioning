"""Unit tests for DataProcessor — grouping, separation, scoring."""

import pytest

from app.data.processor import DataProcessor, SMRegion
from app.models.enums import DealerType, ProductGroup
from helpers import make_dealer, make_ftc, make_relationship


class TestDataProcessorGroupBySM:
    def test_single_sm(self, processor, simple_dealers, simple_ftcs):
        rels = [make_relationship("DLR_A", "FTC_1")]
        regions = processor.group_by_sm(simple_dealers, simple_ftcs, rels)

        assert "SM001" in regions
        region = regions["SM001"]
        assert len(region.dealers) == 3
        assert len(region.ftcs) == 2
        assert len(region.relationships) == 1

    def test_multiple_sm(self, processor, mixed_dealers, mixed_ftcs):
        rels = [
            make_relationship("DLR_SM001_0000", "FTC_SM1_A"),
            make_relationship("DLR_SM002_0000", "FTC_SM2_A"),
        ]
        regions = processor.group_by_sm(mixed_dealers, mixed_ftcs, rels)

        assert "SM001" in regions
        assert "SM002" in regions
        # SM001 has 6 dealers + 2 FTCs
        assert len(regions["SM001"].dealers) == 6
        assert len(regions["SM001"].ftcs) >= 2
        # SM002 has 4 dealers + 1 FTC
        assert len(regions["SM002"].dealers) == 4
        assert len(regions["SM002"].ftcs) == 1

    def test_no_matching_dealers(self, processor):
        ftcs = [make_ftc("F1", sm_id="SM001")]
        regions = processor.group_by_sm([], ftcs, [])
        assert "SM001" in regions
        assert regions["SM001"].dealers == []

    def test_no_matching_ftcs(self, processor):
        dealers = [make_dealer("D1", sm_id="SM001")]
        regions = processor.group_by_sm(dealers, [], [])
        assert "SM001" in regions
        assert regions["SM001"].ftcs == []

    def test_empty_inputs(self, processor):
        regions = processor.group_by_sm([], [], [])
        assert regions == {}

    def test_sm_region_type(self, processor, simple_dealers, simple_ftcs):
        rels = [make_relationship("DLR_A", "FTC_1")]
        regions = processor.group_by_sm(simple_dealers, simple_ftcs, rels)
        region = regions["SM001"]
        assert isinstance(region, SMRegion)
        assert region.sm_id == "SM001"


class TestDataProcessorSeparateDealerTypes:
    def test_separate_both_types(self, processor, mixed_dealers):
        static, mobile = processor.separate_dealer_types(mixed_dealers)
        assert all(d.Dealer_type == DealerType.STATIC for d in static)
        assert all(d.Dealer_type == DealerType.MOBILE for d in mobile)
        # SM001: 4 mobile + 2 static; SM002: 3 mobile + 1 static = 7 mobile, 3 static
        assert len(mobile) == 7
        assert len(static) == 3

    def test_all_mobile(self, processor):
        dealers = [
            make_dealer("D1", dealer_type=DealerType.MOBILE),
            make_dealer("D2", dealer_type=DealerType.MOBILE),
        ]
        static, mobile = processor.separate_dealer_types(dealers)
        assert len(static) == 0
        assert len(mobile) == 2

    def test_all_static(self, processor):
        dealers = [
            make_dealer("D1", dealer_type=DealerType.STATIC),
            make_dealer("D2", dealer_type=DealerType.STATIC),
        ]
        static, mobile = processor.separate_dealer_types(dealers)
        assert len(static) == 2
        assert len(mobile) == 0

    def test_empty(self, processor):
        static, mobile = processor.separate_dealer_types([])
        assert len(static) == 0
        assert len(mobile) == 0


class TestDataProcessorScoring:
    def test_ftc_capacity_default(self, processor):
        ftc = make_ftc("F1")
        cap = processor.compute_ftc_capacity(ftc)
        # 30 * 0.35 + 50 * 0.15 + 0.5 * 0.15 + 0.3 * 0.2 + 0.2 * 0.15
        expected = 30.0 * 0.35 + 50.0 * 0.15 + 0.5 * 0.15 + 0.3 * 0.20 + 0.2 * 0.15
        assert abs(cap - expected) < 1e-6

    def test_ftc_capacity_zero(self, processor):
        ftc = make_ftc("F1", cases=0, disbursements=0, mob=0, ntb=0, cross_sell=0)
        cap = processor.compute_ftc_capacity(ftc)
        assert cap == 0.0

    def test_dealer_importance_mobile(self, processor):
        dealer = make_dealer("D1", dealer_type=DealerType.MOBILE)
        imp = processor.compute_dealer_importance(dealer)
        # 5 * 0.5 + 10 * 0.3 + 0.1
        expected = 5.0 * 0.50 + 10 * 0.30 + 0.10
        assert abs(imp - expected) < 1e-6

    def test_dealer_importance_static(self, processor):
        dealer = make_dealer("D1", dealer_type=DealerType.STATIC)
        imp = processor.compute_dealer_importance(dealer)
        # 5 * 0.5 + 10 * 0.3 + 0.2
        expected = 5.0 * 0.50 + 10 * 0.30 + 0.20
        assert abs(imp - expected) < 1e-6

    def test_dealer_importance_zero(self, processor):
        dealer = make_dealer("D1", cases=0, disbursements=0, dealer_type=DealerType.MOBILE)
        imp = processor.compute_dealer_importance(dealer)
        assert abs(imp - 0.10) < 1e-6


class TestDataProcessorAnchorSelection:
    def test_anchor_matches_ftc(self, processor):
        dealers = [
            make_dealer("D1", cases=10.0),
            make_dealer("D2", cases=5.0),
            make_dealer("D3", cases=1.0),
        ]
        ftcs = [make_ftc("F1"), make_ftc("F2")]
        anchors = processor.select_anchor_dealers(dealers, ftcs)

        assert len(anchors) == 2
        assert "F1" in anchors
        assert "F2" in anchors
        # Highest-cases dealer assigned first
        assert anchors["F1"].Dealer_id == "D1"
        assert anchors["F2"].Dealer_id == "D2"

    def test_anchor_fewer_dealers_than_ftcs(self, processor):
        dealers = [make_dealer("D1", cases=10.0)]
        ftcs = [make_ftc("F1"), make_ftc("F2")]
        anchors = processor.select_anchor_dealers(dealers, ftcs)

        assert len(anchors) == 1  # Only one dealer available
        assert "F1" in anchors

    def test_anchor_empty_dealers(self, processor):
        ftcs = [make_ftc("F1")]
        anchors = processor.select_anchor_dealers([], ftcs)
        assert anchors == {}

    def test_anchor_empty_ftcs(self, processor):
        dealers = [make_dealer("D1")]
        anchors = processor.select_anchor_dealers(dealers, [])
        assert anchors == {}

    def test_anchor_sorted_by_cases(self, processor):
        dealers = [
            make_dealer("D_low", cases=1.0),
            make_dealer("D_high", cases=100.0),
            make_dealer("D_mid", cases=50.0),
        ]
        ftcs = [make_ftc("F1"), make_ftc("F2"), make_ftc("F3")]
        anchors = processor.select_anchor_dealers(dealers, ftcs)

        assert anchors["F1"].Dealer_id == "D_high"
        assert anchors["F2"].Dealer_id == "D_mid"
        assert anchors["F3"].Dealer_id == "D_low"
