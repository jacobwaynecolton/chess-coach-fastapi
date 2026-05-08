from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.mistake_event import MistakeEvent


def build_recommendations(db: Session, top_n: int = 5) -> list[dict]:
    rows = (
        db.query(
            MistakeEvent.category.label("category"),
            MistakeEvent.phase.label("phase"),
            func.count(MistakeEvent.id).label("occurrences"),
            func.avg(MistakeEvent.eval_loss_cp).label("avg_eval_loss_cp"),
        )
        .group_by(MistakeEvent.category, MistakeEvent.phase)
        .all()
    )

    ranked = []
    for row in rows:
        occurrences = int(row.occurrences)
        avg_loss = float(row.avg_eval_loss_cp or 0.0)
        # Prioritize frequent and high-impact patterns.
        priority = occurrences * avg_loss
        ranked.append(
            {
                "category": row.category,
                "phase": row.phase,
                "occurrences": occurrences,
                "avg_eval_loss_cp": avg_loss,
                "priority_score": priority,
                "recommendation": _recommendation_text(row.category, row.phase),
            }
        )

    ranked.sort(key=lambda item: item["priority_score"], reverse=True)
    return ranked[:top_n]


def _recommendation_text(category: str, phase: str) -> str:
    if phase == "opening":
        return (
            "Review your first 10-15 moves and build a simple repertoire tree "
            "with model lines and common tactical traps."
        )
    if phase == "middlegame":
        if category == "blunder":
            return (
                "Run a daily blunder-check routine: before every move, scan "
                "checks/captures/threats for both sides."
            )
        return (
            "Train tactical pattern sets (forks, pins, discovered attacks) and "
            "pause 10 seconds before committing forcing moves."
        )
    return (
        "Practice conversion and defense endgames (king activity, pawn races, "
        "basic rook endings) with slow calculation."
    )
