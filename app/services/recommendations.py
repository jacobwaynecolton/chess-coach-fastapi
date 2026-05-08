from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.mistake_event import MistakeEvent

_CATEGORY_ADVICE: dict[str, str] = {
    "missed_checkmate": (
        "You missed forced checkmates. Drill mating patterns (back-rank, smothered, "
        "two-rook roller) and always scan for forcing sequences before any other plan."
    ),
    "missed_winning_check": (
        "Practice tactical alertness by scanning all checks before each move. "
        "Checks often unlock material gains or decisive positional advantages."
    ),
    "missed_free_material": (
        "You regularly miss undefended opponent pieces. Before every move, apply "
        "the CCT rule: scan for Checks, Captures, and Threats — for both sides."
    ),
    "hanging_piece": (
        "You frequently leave pieces undefended after your moves. After choosing a "
        "move, pause and ask 'does this leave anything hanging?' before playing it."
    ),
    "pawn_overextension": (
        "Avoid pushing kingside pawns past the 5th rank when your king is castled "
        "there — over-advanced pawns become targets and strip your king's cover. "
        "Study Silman's pawn structure chapters or Nimzowitsch on overextension."
    ),
    "king_safety": (
        "Do not push pawns directly in front of your castled king without a concrete "
        "reason. Each pawn move near your king weakens your defensive cover and can "
        "open lines for the opponent's attack."
    ),
}


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
    if category in _CATEGORY_ADVICE:
        return _CATEGORY_ADVICE[category]
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
