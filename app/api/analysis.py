import chess.engine
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import STOCKFISH_PATH
from app.core.database import get_db
from app.models.game import Game
from app.schemas.analysis import AnalysisBatchResponse, AnalysisRunResponse
from app.services.stockfish_analysis import analyze_game

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/engine-status")
def engine_status() -> dict[str, str | bool]:
    exists = Path(STOCKFISH_PATH).exists() or shutil.which(STOCKFISH_PATH) is not None
    return {"stockfish_path": STOCKFISH_PATH, "configured": exists}


@router.post("/run/{game_id}", response_model=AnalysisRunResponse)
def run_analysis_for_game(
    game_id: int,
    depth: int = Query(default=12, ge=6, le=24),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.id == game_id).first()
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found.")

    try:
        analyzed_moves = analyze_game(db=db, game=game, depth=depth)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Stockfish binary not found at '{STOCKFISH_PATH}'. "
                "Set STOCKFISH_PATH env var."
            ),
        ) from exc
    except chess.engine.EngineError as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc}") from exc

    return AnalysisRunResponse(game_id=game_id, analyzed_moves=analyzed_moves)


@router.post("/run-all", response_model=AnalysisBatchResponse)
def run_analysis_for_all_games(
    depth: int = Query(default=12, ge=6, le=24),
    limit: int = Query(default=100, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    games = db.query(Game).order_by(Game.id.asc()).limit(limit).all()
    if not games:
        return AnalysisBatchResponse(analyzed_games=0, analyzed_moves=0)

    total_moves = 0
    analyzed_games = 0
    for game in games:
        try:
            moves = analyze_game(db=db, game=game, depth=depth)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Stockfish binary not found at '{STOCKFISH_PATH}'. "
                    "Set STOCKFISH_PATH env var."
                ),
            ) from exc
        except chess.engine.EngineError as exc:
            raise HTTPException(status_code=500, detail=f"Engine error: {exc}") from exc

        analyzed_games += 1
        total_moves += moves

    return AnalysisBatchResponse(
        analyzed_games=analyzed_games, analyzed_moves=total_moves
    )
