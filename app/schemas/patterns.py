from pydantic import BaseModel


class PatternRunResponse(BaseModel):
    game_id: int
    tagged_events: int


class PatternItem(BaseModel):
    category: str
    phase: str
    occurrences: int
    avg_eval_loss_cp: float


class PatternSummaryResponse(BaseModel):
    total_events: int
    top_patterns: list[PatternItem]


class RecommendationItem(BaseModel):
    category: str
    phase: str
    occurrences: int
    avg_eval_loss_cp: float
    priority_score: float
    recommendation: str


class RecommendationResponse(BaseModel):
    items: list[RecommendationItem]
