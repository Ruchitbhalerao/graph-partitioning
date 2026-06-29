from typing import List, Dict, Tuple
from ..models.schemas import DealerRecord, FTCRecord, FTCRelationshipRecord
from ..models.enums import DealerType
import math


class DataValidator:
    MAX_LAT = 90.0
    MIN_LAT = -90.0
    MAX_LON = 180.0
    MIN_LON = -180.0

    def validate(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
    ) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        errors.extend(self._validate_dealers(dealers))
        errors.extend(self._validate_ftcs(ftcs))
        errors.extend(self._validate_relationships(rels, dealers, ftcs))
        errors.extend(self._validate_cross_references(dealers, ftcs, rels))
        errors.extend(self._validate_sm_consistency(dealers, ftcs))
        return len(errors) == 0, errors

    def _validate_dealers(self, dealers: List[DealerRecord]) -> List[str]:
        errors = []
        seen_ids: Dict[str, int] = {}
        for i, d in enumerate(dealers):
            if d.Dealer_id in seen_ids:
                errors.append(
                    f"Duplicate Dealer_id '{d.Dealer_id}' at rows "
                    f"{seen_ids[d.Dealer_id]} and {i}"
                )
            seen_ids[d.Dealer_id] = i

            if not self._is_valid_lat(d.Dealer_latitude):
                errors.append(f"Dealer '{d.Dealer_id}': invalid latitude {d.Dealer_latitude}")

            if not self._is_valid_lon(d.Dealer_longitude):
                errors.append(f"Dealer '{d.Dealer_id}': invalid longitude {d.Dealer_longitude}")

            if d.Dealer_type == DealerType.STATIC and d.Average_cases_per_day <= 0:
                errors.append(f"Static dealer '{d.Dealer_id}' must have Average_cases_per_day > 0")

            if d.Count_BFL_disbursement < 0:
                errors.append(f"Dealer '{d.Dealer_id}': negative disbursement count")

            if d.Average_cases_per_day < 0:
                errors.append(f"Dealer '{d.Dealer_id}': negative average cases")
        return errors

    def _validate_ftcs(self, ftcs: List[FTCRecord]) -> List[str]:
        errors = []
        seen_ids: Dict[str, int] = {}
        for i, f in enumerate(ftcs):
            if f.FTC_id in seen_ids:
                errors.append(
                    f"Duplicate FTC_id '{f.FTC_id}' at rows "
                    f"{seen_ids[f.FTC_id]} and {i}"
                )
            seen_ids[f.FTC_id] = i

            if f.FTC_VIntage < 0:
                errors.append(f"FTC '{f.FTC_id}': negative vintage")

            if f.Count_BFL_disbursement < 0:
                errors.append(f"FTC '{f.FTC_id}': negative disbursement count")

            if f.Average_cases_per_day < 0:
                errors.append(f"FTC '{f.FTC_id}': negative average cases")

            if f.Per_sum_MOB < 0:
                errors.append(f"FTC '{f.FTC_id}': negative Per_sum_MOB")

            if not (0.0 <= f.NTB_share <= 1.0):
                errors.append(f"FTC '{f.FTC_id}': NTB_share {f.NTB_share} out of range [0,1]")

            if f.Cross_sell < 0:
                errors.append(f"FTC '{f.FTC_id}': negative cross-sell value")
        return errors

    def _validate_relationships(
        self,
        rels: List[FTCRelationshipRecord],
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> List[str]:
        errors = []
        dealer_ids = {d.Dealer_id for d in dealers}
        ftc_ids = {f.FTC_id for f in ftcs}
        for i, r in enumerate(rels):
            if r.Dealer_id not in dealer_ids:
                errors.append(f"Relationship row {i}: Dealer_id '{r.Dealer_id}' not found in Dealers sheet")
            if r.FTC_id not in ftc_ids:
                errors.append(f"Relationship row {i}: FTC_id '{r.FTC_id}' not found in FTC sheet")
            if r.Avg_cases_per_day < 0:
                errors.append(f"Relationship row {i}: negative Avg_cases_per_day")
        return errors

    def _validate_cross_references(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
    ) -> List[str]:
        errors = []
        dealer_sm = {d.Dealer_id: d.SM_id for d in dealers}
        ftc_sm = {f.FTC_id: f.SM_id for f in ftcs}
        for r in rels:
            ds = dealer_sm.get(r.Dealer_id)
            fs = ftc_sm.get(r.FTC_id)
            if ds is not None and fs is not None and ds != fs:
                errors.append(
                    f"Cross-SM relationship: Dealer '{r.Dealer_id}' (SM={ds}) "
                    f"linked to FTC '{r.FTC_id}' (SM={fs})"
                )
        return errors

    def _validate_sm_consistency(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> List[str]:
        errors = []
        dealer_sms = {d.SM_id for d in dealers}
        ftc_sms = {f.SM_id for f in ftcs}
        only_dealers = dealer_sms - ftc_sms
        only_ftcs = ftc_sms - dealer_sms
        if only_dealers:
            errors.append(f"SM(s) with dealers but no FTCs: {', '.join(sorted(only_dealers))}")
        if only_ftcs:
            errors.append(f"SM(s) with FTCs but no dealers: {', '.join(sorted(only_ftcs))}")
        return errors

    @staticmethod
    def _is_valid_lat(lat: float) -> bool:
        return DataValidator.MIN_LAT <= lat <= DataValidator.MAX_LAT

    @staticmethod
    def _is_valid_lon(lon: float) -> bool:
        return DataValidator.MIN_LON <= lon <= DataValidator.MAX_LON
