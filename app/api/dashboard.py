from pathlib import Path
from threading import Lock
import time
from uuid import uuid4

import chess
import chess.svg

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import UPLOADS_DIR
from app.core.database import SessionLocal, get_db
from app.models.analysis import MoveAnalysis
from app.models.game import Game
from app.models.mistake_event import MistakeEvent
from app.services.chesscom_import import fetch_chesscom_games_as_pgn
from app.services.mistake_tagger import summarize_patterns, tag_game_mistakes
from app.services.pgn_ingest import ingest_pgn_text
from app.services.recommendations import build_recommendations
from app.services.stockfish_analysis import analyze_game

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
_JOB_LOCK = Lock()
_JOBS: dict[str, dict] = {}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    stats = {
        "games": db.query(func.count(Game.id)).scalar() or 0,
        "analyzed_moves": db.query(func.count(MoveAnalysis.id)).scalar() or 0,
        "mistake_events": db.query(func.count(MistakeEvent.id)).scalar() or 0,
    }

    total_events, top_patterns = summarize_patterns(db=db, top_n=6)
    recommendations = build_recommendations(db=db, top_n=5)
    recent_games = db.query(Game).order_by(Game.id.desc()).limit(12).all()

    from app.models.analysis import MoveAnalysis as MA
    recent_mistakes_rows = (
        db.query(MistakeEvent, Game)
        .join(Game, MistakeEvent.game_id == Game.id)
        .order_by(MistakeEvent.id.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "stats": stats,
            "total_events": total_events,
            "top_patterns": top_patterns,
            "recommendations": recommendations,
            "recent_games": recent_games,
            "recent_mistakes": recent_mistakes_rows,
            "message": request.query_params.get("message", ""),
        },
    )


@router.post("/dashboard/upload")
async def dashboard_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
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
    (UPLOADS_DIR / source_name).write_text(pgn_text, encoding="utf-8")

    saved_games = ingest_pgn_text(db=db, pgn_text=pgn_text, source_file=source_name)
    return RedirectResponse(
        url=f"/?message=Uploaded+{saved_games}+game(s)+from+{source_name}",
        status_code=303,
    )


@router.post("/dashboard/run-all/start")
def dashboard_run_all_start(
    background_tasks: BackgroundTasks,
    depth: int = Form(default=12),
    limit: int = Form(default=5000),
    only_new: bool = Form(default=False),
):
    safe_depth = max(6, min(depth, 24))
    safe_limit = max(1, min(limit, 20000))
    job_id = uuid4().hex
    with _JOB_LOCK:
        _JOBS[job_id] = {
            "status": "queued",
            "processed_games": 0,
            "total_games": 0,
            "analyzed_moves": 0,
            "tagged_events": 0,
            "skipped_games": 0,
            "only_new": only_new,
            "cancel_requested": False,
            "elapsed_seconds": 0,
            "eta_seconds": None,
            "message": "Starting pipeline...",
        }
    background_tasks.add_task(_run_pipeline_job, job_id, safe_depth, safe_limit, only_new)
    return JSONResponse({"job_id": job_id})


@router.get("/dashboard/jobs/{job_id}")
def dashboard_job_status(job_id: str):
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/dashboard/jobs/{job_id}/cancel")
def dashboard_job_cancel(job_id: str):
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if job["status"] in {"completed", "failed", "cancelled"}:
            return {"ok": True, "status": job["status"]}
        job["cancel_requested"] = True
        job["message"] = "Cancellation requested. Stopping after current game..."
    return {"ok": True, "status": "cancelling"}


def _run_pipeline_job(job_id: str, depth: int, limit: int, only_new: bool) -> None:
    db = SessionLocal()
    started = time.monotonic()
    try:
        games = db.query(Game).order_by(Game.id.asc()).all()
        if only_new:
            analyzed_ids = {
                game_id for (game_id,) in db.query(MoveAnalysis.game_id).distinct().all()
            }
            tagged_ids = {
                game_id for (game_id,) in db.query(MistakeEvent.game_id).distinct().all()
            }
            games = [
                game for game in games if game.id not in analyzed_ids or game.id not in tagged_ids
            ]
        games = games[:limit]
        total_games = len(games)
        with _JOB_LOCK:
            _JOBS[job_id]["status"] = "running"
            _JOBS[job_id]["total_games"] = total_games
            _JOBS[job_id]["message"] = "Analyzing games..."

        analyzed_moves = 0
        tagged_events = 0
        processed_games = 0
        skipped_games = 0
        for game in games:
            with _JOB_LOCK:
                cancel_requested = bool(_JOBS[job_id].get("cancel_requested"))
            if cancel_requested:
                with _JOB_LOCK:
                    _JOBS[job_id]["status"] = "cancelled"
                    _JOBS[job_id]["message"] = (
                        f"Cancelled after {processed_games} processed games."
                    )
                return

            if only_new:
                has_analysis = (
                    db.query(func.count(MoveAnalysis.id))
                    .filter(MoveAnalysis.game_id == game.id)
                    .scalar()
                    or 0
                ) > 0
                has_tags = (
                    db.query(func.count(MistakeEvent.id))
                    .filter(MistakeEvent.game_id == game.id)
                    .scalar()
                    or 0
                ) > 0
                if has_analysis and has_tags:
                    skipped_games += 1
                    continue

            analyzed_moves += analyze_game(db=db, game=game, depth=depth)
            tagged_events += tag_game_mistakes(db=db, game_id=game.id)
            processed_games += 1
            elapsed = int(time.monotonic() - started)
            eta = None
            if processed_games > 0 and total_games > processed_games:
                seconds_per_game = elapsed / processed_games
                eta = int((total_games - processed_games) * seconds_per_game)
            with _JOB_LOCK:
                _JOBS[job_id]["processed_games"] = processed_games
                _JOBS[job_id]["analyzed_moves"] = analyzed_moves
                _JOBS[job_id]["tagged_events"] = tagged_events
                _JOBS[job_id]["skipped_games"] = skipped_games
                _JOBS[job_id]["elapsed_seconds"] = elapsed
                _JOBS[job_id]["eta_seconds"] = eta
                _JOBS[job_id]["message"] = (
                    f"Processed {processed_games}/{total_games} games..."
                )

        with _JOB_LOCK:
            _JOBS[job_id]["status"] = "completed"
            _JOBS[job_id]["elapsed_seconds"] = int(time.monotonic() - started)
            _JOBS[job_id]["eta_seconds"] = 0
            _JOBS[job_id]["message"] = (
                f"Done. Processed {processed_games} games, analyzed {analyzed_moves} moves, "
                f"tagged {tagged_events} events, skipped {skipped_games}."
            )
    except Exception as exc:  # noqa: BLE001
        with _JOB_LOCK:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["message"] = f"Pipeline failed: {exc}"
    finally:
        db.close()


@router.post("/dashboard/clear-mistakes")
def dashboard_clear_mistakes(db: Session = Depends(get_db)):
    db.query(MistakeEvent).delete()
    db.commit()
    return RedirectResponse(url="/?message=Mistake+data+cleared.", status_code=303)


@router.get("/mistakes/{mistake_id}/board")
def mistake_board_svg(mistake_id: int, db: Session = Depends(get_db)):
    mistake = db.query(MistakeEvent).filter(MistakeEvent.id == mistake_id).first()
    if mistake is None or not mistake.fen_after:
        raise HTTPException(status_code=404, detail="No board data for this mistake.")

    board = chess.Board(mistake.fen_after)
    flipped = mistake.side_to_move == "black"
    fill: dict[chess.Square, str] = {}

    mover_color = chess.WHITE if mistake.side_to_move == "white" else chess.BLACK
    opponent_color = not mover_color

    if mistake.category == "hanging_piece":
        # Highlight every piece that is attacked but has no defender, so it's obvious at a glance.
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.color == mover_color and piece.piece_type != chess.KING:
                if board.is_attacked_by(opponent_color, sq) and not board.is_attacked_by(mover_color, sq):
                    fill[sq] = "#cc333377"

    elif mistake.category == "missed_free_material":
        # Highlight undefended opponent pieces that were available to capture for free.
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.color == opponent_color and piece.piece_type != chess.KING:
                if not board.is_attacked_by(opponent_color, sq):
                    fill[sq] = "#22bb4477"

    lastmove = None
    analysis = db.query(MoveAnalysis).filter(MoveAnalysis.id == mistake.analysis_id).first()
    if analysis and analysis.played_move_uci:
        try:
            lastmove = chess.Move.from_uci(analysis.played_move_uci)
        except Exception:
            pass

    svg = chess.svg.board(board=board, fill=fill, lastmove=lastmove, flipped=flipped, size=380)
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/dashboard/retag-all/start")
def dashboard_retag_all_start(background_tasks: BackgroundTasks):
    job_id = uuid4().hex
    with _JOB_LOCK:
        _JOBS[job_id] = {
            "status": "queued",
            "processed_games": 0,
            "total_games": 0,
            "analyzed_moves": 0,
            "tagged_events": 0,
            "skipped_games": 0,
            "only_new": False,
            "cancel_requested": False,
            "elapsed_seconds": 0,
            "eta_seconds": None,
            "message": "Starting retag...",
        }
    background_tasks.add_task(_run_retag_job, job_id)
    return JSONResponse({"job_id": job_id})


def _run_retag_job(job_id: str) -> None:
    db = SessionLocal()
    started = time.monotonic()
    try:
        analyzed_game_ids = [
            gid for (gid,) in db.query(MoveAnalysis.game_id).distinct().all()
        ]
        total_games = len(analyzed_game_ids)
        with _JOB_LOCK:
            _JOBS[job_id]["status"] = "running"
            _JOBS[job_id]["total_games"] = total_games
            _JOBS[job_id]["message"] = "Re-tagging mistakes with improved pattern detection..."

        tagged_events = 0
        for i, game_id in enumerate(analyzed_game_ids):
            with _JOB_LOCK:
                if _JOBS[job_id].get("cancel_requested"):
                    _JOBS[job_id]["status"] = "cancelled"
                    _JOBS[job_id]["message"] = f"Cancelled after {i} games."
                    return

            tagged_events += tag_game_mistakes(db=db, game_id=game_id)
            processed = i + 1
            elapsed = int(time.monotonic() - started)
            eta = int((total_games - processed) * (elapsed / processed)) if processed > 0 and total_games > processed else 0
            with _JOB_LOCK:
                _JOBS[job_id]["processed_games"] = processed
                _JOBS[job_id]["tagged_events"] = tagged_events
                _JOBS[job_id]["elapsed_seconds"] = elapsed
                _JOBS[job_id]["eta_seconds"] = eta
                _JOBS[job_id]["message"] = f"Re-tagged {processed}/{total_games} games..."

        with _JOB_LOCK:
            _JOBS[job_id]["status"] = "completed"
            _JOBS[job_id]["elapsed_seconds"] = int(time.monotonic() - started)
            _JOBS[job_id]["eta_seconds"] = 0
            _JOBS[job_id]["message"] = (
                f"Done. Re-tagged {total_games} games, {tagged_events} events updated."
            )
    except Exception as exc:
        with _JOB_LOCK:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["message"] = f"Retag failed: {exc}"
    finally:
        db.close()


@router.post("/dashboard/import-chesscom")
def dashboard_import_chesscom(
    username: str = Form(...),
    db: Session = Depends(get_db),
):
    cleaned_username = username.strip()
    if not cleaned_username:
        raise HTTPException(status_code=400, detail="Chess.com username is required.")

    try:
        pgn_text, fetched_games = fetch_chesscom_games_as_pgn(cleaned_username)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not pgn_text:
        return RedirectResponse(
            url=f"/?message=No+games+found+for+Chess.com+user+{cleaned_username}",
            status_code=303,
        )

    source_name = f"chesscom-{cleaned_username}.pgn"
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / source_name).write_text(pgn_text, encoding="utf-8")
    saved_games = ingest_pgn_text(db=db, pgn_text=pgn_text, source_file=source_name)

    return RedirectResponse(
        url=(
            "/?message="
            f"Imported+{saved_games}+game(s)+from+Chess.com+user+{cleaned_username}"
            f"+%28fetched+{fetched_games}%29"
        ),
        status_code=303,
    )
