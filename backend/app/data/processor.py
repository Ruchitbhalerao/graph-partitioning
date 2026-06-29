from typing import List, Dict, DefaultDict
from collections import defaultdict
from ..models.schemas import DealerRecord, FTCRecord, FTCRelationshipRecord
from ..models.enums import DealerType


class SMRegion:
    def __init__(self, sm_id: str):
        self.sm_id = sm_id
        self.dealers: List[DealerRecord] = []
        self.ftcs: List[FTCRecord] = []
        self.relationships: List[FTCRelationshipRecord] = []


class DataProcessor:
    def group_by_sm(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
    ) -> Dict[str, SMRegion]:
        dealer_map: Dict[str, List[DealerRecord]] = defaultdict(list)
        for d in dealers:
            dealer_map[d.SM_id].append(d)

        ftc_map: Dict[str, List[FTCRecord]] = defaultdict(list)
        for f in ftcs:
            ftc_map[f.SM_id].append(f)

        rel_map: Dict[str, List[FTCRelationshipRecord]] = defaultdict(list)
        for r in rels:
            dealer_sm = None
            for d in dealers:
                if d.Dealer_id == r.Dealer_id:
                    dealer_sm = d.SM_id
                    break
            if dealer_sm:
                rel_map[dealer_sm].append(r)

        all_sm_ids = set(dealer_map.keys()) | set(ftc_map.keys())
        regions = {}
        for sm_id in all_sm_ids:
            region = SMRegion(sm_id)
            region.dealers = dealer_map.get(sm_id, [])
            region.ftcs = ftc_map.get(sm_id, [])
            region.relationships = rel_map.get(sm_id, [])
            regions[sm_id] = region

        return regions

    def separate_dealer_types(
        self, dealers: List[DealerRecord]
    ) -> tuple[List[DealerRecord], List[DealerRecord]]:
        static = [d for d in dealers if d.Dealer_type == DealerType.STATIC]
        mobile = [d for d in dealers if d.Dealer_type == DealerType.MOBILE]
        return static, mobile

    def compute_ftc_capacity(self, ftc: FTCRecord) -> float:
        return (
            ftc.Average_cases_per_day * 0.35
            + ftc.Count_BFL_disbursement * 0.15
            + ftc.Per_sum_MOB * 0.15
            + ftc.NTB_share * 0.20
            + ftc.Cross_sell * 0.15
        )

    def compute_dealer_importance(self, dealer: DealerRecord) -> float:
        return (
            dealer.Average_cases_per_day * 0.50
            + dealer.Count_BFL_disbursement * 0.30
            + (0.20 if dealer.Dealer_type == DealerType.STATIC else 0.10)
        )

    def select_anchor_dealers(
        self, mobile_dealers: List[DealerRecord], ftcs: List[FTCRecord]
    ) -> Dict[str, DealerRecord]:
        sorted_dealers = sorted(
            mobile_dealers,
            key=lambda d: d.Average_cases_per_day,
            reverse=True
        )
        anchors = {}
        for ftc in ftcs:
            if sorted_dealers:
                anchors[ftc.FTC_id] = sorted_dealers.pop(0)
        return anchors
