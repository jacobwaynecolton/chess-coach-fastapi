from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import UPLOADS_DIR
from app.core.database import get_db
from app.models.game import Game
from app.schemas.game import GameOut, UploadResponse
from app.services.pgn_ingest import ingest_pgn_text

router = APIRouter(prefix="/games", tags=["games"])


@router.post("/upload", response_model=UploadResponse)
async def upload_pgn(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # Start strict with file type; we can relax this later if needed.
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pgn":
        raise HTTPException(status_code=400, detail="Please upload a .pgn file.")

    raw = await file.read()
    try:
        pgn_text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="PGN must be UTF-8 text.") from exc

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    source_name = file.filename or "uploaded.pgn"
    upload_path = UPLOADS_DIR / source_name
    # Keep the original upload around for re-processing/debugging.
    upload_path.write_text(pgn_text, encoding="utf-8")

    saved_games = ingest_pgn_text(db=db, pgn_text=pgn_text, source_file=source_name)
    return UploadResponse(saved_games=saved_games, source_file=source_name)


@router.get("", response_model=list[GameOut])
def list_games(limit: int = 50, db: Session = Depends(get_db)):
    # Guardrails to avoid huge accidental fetches from the UI.
    safe_limit = max(1, min(limit, 500))
    return db.query(Game).order_by(Game.id.desc()).limit(safe_limit).all()
