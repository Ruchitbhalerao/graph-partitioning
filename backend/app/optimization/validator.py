from typing import List, Dict, Tuple, Set
import networkx as nx
from ..models.schemas import DealerRecord, FTCRecord
from ..models.enums import DealerType


class BusinessRuleValidator:
    def validate_all(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        G: nx.Graph,
    ) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        errors.extend(self._validate_no_cross_sm(assignments, dealers, ftcs))
        errors.extend(self._validate_static_fixed(assignments, dealers))
        errors.extend(self._validate_contiguity(assignments, G))
        errors.extend(self._validate_no_overlaps(assignments))
        errors.extend(self._validate_capacity(assignments, dealers, ftcs))
        errors.extend(self._validate_all_assigned(assignments, dealers))
        return len(errors) == 0, errors

    def _validate_no_cross_sm(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> List[str]:
        errors = []
        dealer_sm = {d.Dealer_id: d.SM_id for d in dealers}
        ftc_sm = {f.FTC_id: f.SM_id for f in ftcs}

        for ftc_id, dealer_ids in assignments.items():
            ftc_sm_id = ftc_sm.get(ftc_id)
            if ftc_sm_id is None:
                errors.append(f"FTC '{ftc_id}' has no SM assignment")
                continue
            for dealer_id in dealer_ids:
                dealer_sm_id = dealer_sm.get(dealer_id)
                if dealer_sm_id is not None and dealer_sm_id != ftc_sm_id:
                    errors.append(
                        f"Cross-SM: FTC '{ftc_id}' (SM={ftc_sm_id}) assigned "
                        f"dealer '{dealer_id}' (SM={dealer_sm_id})"
                    )
        return errors

    def _validate_static_fixed(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
    ) -> List[str]:
        errors = []
        static_dealers = {
            d.Dealer_id for d in dealers
            if d.Dealer_type == DealerType.STATIC
        }
        assigned = set()
        for dealer_ids in assignments.values():
            for d in dealer_ids:
                if d in assigned:
                    errors.append(f"Static dealer '{d}' assigned to multiple FTCs")
                assigned.add(d)

        for s in static_dealers:
            if s not in assigned:
                errors.append(f"Static dealer '{s}' has no FTC assignment")
        return errors

    def _validate_contiguity(
        self,
        assignments: Dict[str, List[str]],
        G: nx.Graph,
    ) -> List[str]:
        errors = []
        for ftc_id, dealer_ids in assignments.items():
            if len(dealer_ids) <= 1:
                continue
            subgraph = G.subgraph(dealer_ids)
            if not nx.is_connected(subgraph):
                components = list(nx.connected_components(subgraph))
                errors.append(
                    f"FTC '{ftc_id}' territory has {len(components)} "
                    f"disconnected components"
                )
        return errors

    def _validate_no_overlaps(
        self,
        assignments: Dict[str, List[str]],
    ) -> List[str]:
        errors = []
        all_assigned = {}
        for ftc_id, dealer_ids in assignments.items():
            for d in dealer_ids:
                if d in all_assigned:
                    errors.append(
                        f"Dealer '{d}' assigned to both FTC "
                        f"'{all_assigned[d]}' and '{ftc_id}'"
                    )
                all_assigned[d] = ftc_id
        return errors

    def _validate_capacity(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> List[str]:
        errors = []
        dealer_cases = {d.Dealer_id: d.Average_cases_per_day for d in dealers}
        ftc_cases = {f.FTC_id: f.Average_cases_per_day for f in ftcs}

        for ftc_id, dealer_ids in assignments.items():
            total_cases = sum(dealer_cases.get(d, 0) for d in dealer_ids)
            capacity = ftc_cases.get(ftc_id, 0)
            if capacity > 0 and total_cases > capacity * 1.5:
                errors.append(
                    f"FTC '{ftc_id}' exceeds 150% capacity: "
                    f"{total_cases:.1f} assigned vs {capacity:.1f} capacity"
                )
        return errors

    def _validate_all_assigned(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
    ) -> List[str]:
        errors = []
        all_assigned = set()
        for dealer_ids in assignments.values():
            all_assigned.update(dealer_ids)
        for d in dealers:
            if d.Dealer_id not in all_assigned:
                errors.append(f"Dealer '{d.Dealer_id}' is unassigned")
        return errors
