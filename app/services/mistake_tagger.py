from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analysis import MoveAnalysis
from app.models.mistake_event import MistakeEvent


def tag_game_mistakes(db: Session, game_id: int) -> int:
    db.query(MistakeEvent).filter(MistakeEvent.game_id == game_id).delete()

    rows = (
        db.query(MoveAnalysis)
        .filter(MoveAnalysis.game_id == game_id)
        .order_by(MoveAnalysis.ply.asc())
        .all()
    )

    created = 0
    for row in rows:
        loss = row.eval_loss_cp
        if loss is None:
            continue

        category, severity = _classify_loss(loss)
        if category is None:
            continue

        event = MistakeEvent(
            game_id=game_id,
            analysis_id=row.id,
            ply=row.ply,
            side_to_move=row.side_to_move,
            phase=_phase_for_ply(row.ply),
            category=category,
            severity=severity,
            eval_loss_cp=loss,
        )
        db.add(event)
        created += 1

    db.commit()
    return created


def summarize_patterns(db: Session, top_n: int = 8) -> tuple[int, list[dict]]:
    total = db.query(func.count(MistakeEvent.id)).scalar() or 0
    if total == 0:
        return 0, []

    rows = (
        db.query(
            MistakeEvent.category.label("category"),
            MistakeEvent.phase.label("phase"),
            func.count(MistakeEvent.id).label("occurrences"),
            func.avg(MistakeEvent.eval_loss_cp).label("avg_eval_loss_cp"),
        )
        .group_by(MistakeEvent.category, MistakeEvent.phase)
        .order_by(func.count(MistakeEvent.id).desc())
        .limit(top_n)
        .all()
    )

    patterns = [
        {
            "category": row.category,
            "phase": row.phase,
            "occurrences": int(row.occurrences),
            "avg_eval_loss_cp": float(row.avg_eval_loss_cp or 0.0),
        }
        for row in rows
    ]
    return int(total), patterns


def _classify_loss(eval_loss_cp: float) -> tuple[str | None, str | None]:
    if eval_loss_cp < 50:
        return None, None
    if eval_loss_cp < 100:
        return "inaccuracy", "low"
    if eval_loss_cp < 200:
        return "mistake", "medium"
    return "blunder", "high"


def _phase_for_ply(ply: int) -> str:
    if ply <= 20:
        return "opening"
    if ply <= 60:
        return "middlegame"
    return "endgame"
