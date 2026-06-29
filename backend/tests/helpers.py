"""Shared test helper functions (factories, generators).

Separate from conftest.py to allow direct imports in test modules.
"""

from typing import List, Optional
import math
import random
import uuid

from app.models.schemas import DealerRecord, FTCRecord, FTCRelationshipRecord
from app.models.enums import DealerType, ProductGroup


random.seed(42)


def make_dealer(
    dealer_id: str = None,
    sm_id: str = "SM001",
    dealer_type: DealerType = DealerType.MOBILE,
    product_group: ProductGroup = ProductGroup.PRODUCT_A,
    lat: float = 19.0,
    lng: float = 73.0,
    cases: float = 5.0,
    disbursements: int = 10,
) -> DealerRecord:
    return DealerRecord(
        SM_id=sm_id,
        Dealer_id=dealer_id or f"DLR_{uuid.uuid4().hex[:6]}",
        Dealer_type=dealer_type,
        Product_group=product_group,
        Count_BFL_disbursement=disbursements,
        Average_cases_per_day=cases,
        Dealer_latitude=lat,
        Dealer_longitude=lng,
    )


def make_ftc(
    ftc_id: str = None,
    sm_id: str = "SM001",
    product_group: ProductGroup = ProductGroup.PRODUCT_A,
    vintage: int = 3,
    cases: float = 30.0,
    disbursements: int = 50,
    mob: float = 0.5,
    ntb: float = 0.3,
    cross_sell: float = 0.2,
) -> FTCRecord:
    return FTCRecord(
        FTC_id=ftc_id or f"FTC_{uuid.uuid4().hex[:6]}",
        SM_id=sm_id,
        Product_Group=product_group,
        FTC_VIntage=vintage,
        Count_BFL_disbursement=disbursements,
        Average_cases_per_day=cases,
        Per_sum_MOB=mob,
        NTB_share=ntb,
        Cross_sell=cross_sell,
    )


def make_relationship(
    dealer_id: str,
    ftc_id: str,
    product_category: ProductGroup = ProductGroup.PRODUCT_A,
    avg_cases: float = 3.0,
) -> FTCRelationshipRecord:
    return FTCRelationshipRecord(
        Dealer_id=dealer_id,
        FTC_id=ftc_id,
        Product_category=product_category,
        Avg_cases_per_day=avg_cases,
    )


def generate_cluster(
    center_lat: float,
    center_lng: float,
    count: int,
    sm_id: str = "SM001",
    radius_km: float = 2.0,
    dealer_type: DealerType = DealerType.MOBILE,
) -> List[DealerRecord]:
    dealers = []
    km_per_deg = 111.32
    for i in range(count):
        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(0.1, radius_km)
        dlat = (dist / km_per_deg) * math.cos(angle)
        dlng = (dist / km_per_deg) * math.sin(angle) / math.cos(math.radians(center_lat))
        dealers.append(make_dealer(
            dealer_id=f"DLR_{sm_id}_{i:04d}",
            sm_id=sm_id,
            dealer_type=dealer_type,
            lat=center_lat + dlat,
            lng=center_lng + dlng,
            cases=random.uniform(1.0, 15.0),
            disbursements=random.randint(0, 50),
        ))
    return dealers
