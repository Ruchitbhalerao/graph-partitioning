"""Shared fixtures and test data generators for the entire test suite."""

import os
import sys

# Ensure the tests directory is on sys.path for helper imports
_tests_dir = os.path.dirname(os.path.abspath(__file__))
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from typing import List
import random

import pytest
import networkx as nx
import numpy as np

from app.data.processor import DataProcessor
from app.models.schemas import DealerRecord, FTCRecord, OptimizationConfig
from app.models.enums import DealerType
from app.optimization.graph_builder import DealerGraphBuilder
from app.optimization.partitioner import TerritoryPartitioner
from app.optimization.refiner import TerritoryRefiner
from app.optimization.engine import OptimizationEngine


# ---------------------------------------------------------------------------
# Seed for reproducibility
# ---------------------------------------------------------------------------

random.seed(42)
np.random.seed(42)

# Re-export helpers for direct use in fixtures
from helpers import make_dealer, make_ftc, make_relationship, generate_cluster


# ---------------------------------------------------------------------------
# Pre-built datasets
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def simple_dealers() -> List[DealerRecord]:
    """3 dealers in a line — minimal test case."""
    return [
        make_dealer("DLR_A", lat=19.0, lng=73.0, dealer_type=DealerType.MOBILE, cases=5.0),
        make_dealer("DLR_B", lat=19.01, lng=73.01, dealer_type=DealerType.MOBILE, cases=10.0),
        make_dealer("DLR_C", lat=19.02, lng=73.02, dealer_type=DealerType.MOBILE, cases=3.0),
    ]


@pytest.fixture(scope="session")
def simple_ftcs() -> List[FTCRecord]:
    return [
        make_ftc("FTC_1", cases=18.0),
        make_ftc("FTC_2", cases=18.0),
    ]


@pytest.fixture(scope="session")
def mixed_dealers() -> List[DealerRecord]:
    """Mix of static and mobile dealers across 2 SM regions."""
    dealers = []
    # SM001: 4 mobile, 2 static (static IDs offset to avoid collision)
    dealers.extend(generate_cluster(19.0, 73.0, 4, "SM001", radius_km=1.0, dealer_type=DealerType.MOBILE))
    for i in range(2):
        dealers.append(make_dealer(
            f"DLR_SM001_STAT_{i:04d}", sm_id="SM001", dealer_type=DealerType.STATIC,
            lat=19.01, lng=73.01, cases=3.0,
        ))
    # SM002: 3 mobile, 1 static
    dealers.extend(generate_cluster(28.6, 77.2, 3, "SM002", radius_km=1.5, dealer_type=DealerType.MOBILE))
    dealers.append(make_dealer(
        "DLR_SM002_STATIC", sm_id="SM002", dealer_type=DealerType.STATIC,
        lat=28.61, lng=77.21, cases=8.0,
    ))
    return dealers


@pytest.fixture(scope="session")
def mixed_ftcs() -> List[FTCRecord]:
    return [
        make_ftc("FTC_SM1_A", sm_id="SM001", cases=20.0),
        make_ftc("FTC_SM1_B", sm_id="SM001", cases=25.0),
        make_ftc("FTC_SM2_A", sm_id="SM002", cases=30.0),
    ]


@pytest.fixture(scope="session")
def many_dealers() -> List[DealerRecord]:
    """Large dataset: 500 dealers across 5 SM regions for performance tests."""
    dealers = []
    centers = [
        (19.0, 73.0, "SM001"),
        (28.6, 77.2, "SM002"),
        (13.0, 80.0, "SM003"),
        (22.5, 88.3, "SM004"),
        (17.4, 78.5, "SM005"),
    ]
    for sm_idx, (lat, lng, sm_id) in enumerate(centers):
        mobile = generate_cluster(lat, lng, 80, sm_id, radius_km=3.0, dealer_type=DealerType.MOBILE)
        dealers.extend(mobile)
        # Static dealers use unique IDs (offset by 1000) to avoid collision with mobile
        for i in range(20):
            dealers.append(make_dealer(
                f"DLR_{sm_id}_STAT_{i:04d}", sm_id=sm_id, dealer_type=DealerType.STATIC,
                lat=lat + 0.02 + (i * 0.001), lng=lng + 0.02,
                cases=random.uniform(1.0, 10.0),
                disbursements=random.randint(0, 30),
            ))
    return dealers


@pytest.fixture(scope="session")
def many_ftcs() -> List[FTCRecord]:
    """FTCs for the large dataset."""
    ftcs = []
    for sm_id in ["SM001", "SM002", "SM003", "SM004", "SM005"]:
        for i in range(20):
            ftcs.append(make_ftc(
                f"FTC_{sm_id}_{i:02d}", sm_id=sm_id,
                cases=random.uniform(15.0, 60.0),
            ))
    return ftcs


@pytest.fixture(scope="session")
def config() -> OptimizationConfig:
    return OptimizationConfig(
        travel_weight=0.35,
        workload_weight=0.30,
        compactness_weight=0.20,
        productivity_weight=0.15,
        proximity_km=5.0,
        preserve_existing=False,
        max_refinement_iterations=50,
    )


@pytest.fixture(scope="session")
def tight_config() -> OptimizationConfig:
    return OptimizationConfig(
        travel_weight=0.4,
        workload_weight=0.4,
        compactness_weight=0.1,
        productivity_weight=0.1,
        proximity_km=2.0,
        preserve_existing=False,
        max_refinement_iterations=10,
    )


# ---------------------------------------------------------------------------
# Graph fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_graph(simple_dealers) -> nx.Graph:
    builder = DealerGraphBuilder(proximity_km=5.0)
    return builder.build(simple_dealers)


@pytest.fixture
def mixed_graph(mixed_dealers, mixed_ftcs) -> nx.Graph:
    builder = DealerGraphBuilder(proximity_km=5.0)
    return builder.build(mixed_dealers, mixed_ftcs)


@pytest.fixture
def many_graph(many_dealers, many_ftcs) -> nx.Graph:
    builder = DealerGraphBuilder(proximity_km=3.0)
    return builder.build(many_dealers, many_ftcs)


# ---------------------------------------------------------------------------
# Engine fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine(config) -> OptimizationEngine:
    return OptimizationEngine(config)


@pytest.fixture
def tight_engine(tight_config) -> OptimizationEngine:
    return OptimizationEngine(tight_config)


# ---------------------------------------------------------------------------
# Service fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def processor() -> DataProcessor:
    return DataProcessor()


@pytest.fixture
def validator() -> DataValidator:
    return DataValidator()


@pytest.fixture
def business_rule_validator() -> BusinessRuleValidator:
    return BusinessRuleValidator()


@pytest.fixture
def partitioner() -> TerritoryPartitioner:
    builder = DealerGraphBuilder(proximity_km=5.0)
    return TerritoryPartitioner(builder)


@pytest.fixture
def refiner() -> TerritoryRefiner:
    builder = DealerGraphBuilder(proximity_km=5.0)
    return TerritoryRefiner(
        graph_builder=builder,
        max_iterations=20,
        stagnation_limit=5,
        tabu_tenure=3,
        verbose=False,
    )


# ---------------------------------------------------------------------------
# API test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    from app.main import create_app
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()
