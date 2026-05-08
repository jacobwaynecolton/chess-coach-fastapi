from pydantic import BaseModel


class AnalysisRunResponse(BaseModel):
    game_id: int
    analyzed_moves: int


class AnalysisBatchResponse(BaseModel):
    analyzed_games: int
    analyzed_moves: int
