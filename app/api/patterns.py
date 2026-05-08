from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.game import Game
from app.schemas.patterns import PatternRunResponse, PatternSummaryResponse
from app.services.mistake_tagger import summarize_patterns, tag_game_mistakes

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.post("/run/{game_id}", response_model=PatternRunResponse)
def run_pattern_tagging(game_id: int, db: Session = Depends(get_db)):
    game = db.query(Game).filter(Game.id == game_id).first()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found.")

    tagged_events = tag_game_mistakes(db=db, game_id=game_id)
    return PatternRunResponse(game_id=game_id, tagged_events=tagged_events)


@router.get("/summary", response_model=PatternSummaryResponse)
def get_pattern_summary(
    top_n: int = Query(default=8, ge=1, le=25),
    db: Session = Depends(get_db),
):
    total_events, top_patterns = summarize_patterns(db=db, top_n=top_n)
    return PatternSummaryResponse(total_events=total_events, top_patterns=top_patterns)
