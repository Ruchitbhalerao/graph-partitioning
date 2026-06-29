from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from .enums import OptimizationPhase


class SMProgress(BaseModel):
    sm_id: str
    status: str = "pending"
    dealers_count: int = 0
    ftcs_count: int = 0
    partition_time: float = 0.0
    refine_time: float = 0.0
    refine_iterations: int = 0
    refine_improvement_pct: float = 0.0
    is_valid: bool = True
    errors: List[str] = []


class RefinerIteration(BaseModel):
    iteration: int
    fitness: float
    best_fitness: float
    travel_penalty: float = 0.0
    workload_penalty: float = 0.0
    compactness_penalty: float = 0.0
    moves_accepted: int = 0
    stagnation: int = 0


class PhaseTiming(BaseModel):
    phase: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: float = 0.0


class OptimizationProgressEvent(BaseModel):
    job_id: str
    phase: OptimizationPhase = OptimizationPhase.GRAPH_CONSTRUCTION
    progress: float = 0.0
    message: str = ""
    current_sm: Optional[str] = None
    sm_total: int = 0
    sm_completed: int = 0
    sm_progress: Optional[SMProgress] = None
    refiner_iteration: Optional[RefinerIteration] = None
    timing: List[PhaseTiming] = []
    error: Optional[str] = None
    estimated_remaining_sec: Optional[float] = None
    timestamp: datetime = None

    class Config:
        use_enum_values = True

    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] is None:
            data["timestamp"] = datetime.now()
        super().__init__(**data)
