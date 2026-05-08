from io import StringIO

import chess
import chess.pgn
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analysis import MoveAnalysis
from app.models.game import Game
from app.models.mistake_event import MistakeEvent

_PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


def tag_game_mistakes(db: Session, game_id: int) -> int:
    db.query(MistakeEvent).filter(MistakeEvent.game_id == game_id).delete()

    # Replay the PGN so we have the exact board state at every ply for position-aware diagnosis.
    position_map: dict[int, chess.Board] = {}
    game_row = db.query(Game).filter(Game.id == game_id).first()
    if game_row and game_row.pgn_text:
        try:
            parsed = chess.pgn.read_game(StringIO(game_row.pgn_text))
            if parsed:
                board = parsed.board()
                for ply, move in enumerate(parsed.mainline_moves(), start=1):
                    position_map[ply] = board.copy()
                    board.push(move)
        except Exception:
            pass

    rows = (
        db.query(MoveAnalysis)
        .filter(MoveAnalysis.game_id == game_id)
        .order_by(MoveAnalysis.ply.asc())
        .all()
    )

    created = 0
    for row in rows:
        loss = row.eval_loss_cp
        if loss is None or loss < 50:
            continue

        severity = _severity_from_loss(loss)
        board_before = position_map.get(row.ply)

        try:
            played = chess.Move.from_uci(row.played_move_uci) if row.played_move_uci else None
            best = chess.Move.from_uci(row.best_move_uci) if row.best_move_uci else None
        except Exception:
            played, best = None, None

        fen_after = None
        category = severity
        description = _fallback_description(severity, loss)

        if board_before is not None and played is not None:
            try:
                board_after = board_before.copy()
                board_after.push(played)
                fen_after = board_after.fen()
            except Exception:
                pass

            category, description = _diagnose_mistake(board_before, played, best, loss)

        event = MistakeEvent(
            game_id=game_id,
            analysis_id=row.id,
            ply=row.ply,
            side_to_move=row.side_to_move,
            phase=_phase_for_ply(row.ply),
            category=category,
            severity=severity,
            eval_loss_cp=loss,
            description=description,
            fen_after=fen_after,
        )
        db.add(event)
        created += 1

    db.commit()
    return created


def _diagnose_mistake(
    board: chess.Board,
    played: chess.Move,
    best: chess.Move | None,
    loss: float,
) -> tuple[str, str]:
    mover = board.turn

    # Checkmate is the highest-priority pattern — if it was available and missed, that's the story.
    if best is not None:
        try:
            test = board.copy()
            test.push(best)
            if test.is_checkmate():
                return (
                    "missed_checkmate",
                    "You had a forced checkmate available in this position but didn't play it.",
                )
            if test.is_check() and loss >= 150:
                return (
                    "missed_winning_check",
                    "You missed a check that would have won significant material.",
                )
        except Exception:
            pass

    # A piece is truly free only if the opponent has no recapture available.
    if best is not None:
        try:
            if board.is_capture(best) and not board.is_capture(played):
                captured = board.piece_at(best.to_square)
                if captured is not None and captured.piece_type != chess.PAWN:
                    if not board.is_attacked_by(not mover, best.to_square):
                        piece_name = _PIECE_NAMES[captured.piece_type]
                        sq_name = chess.square_name(best.to_square)
                        return (
                            "missed_free_material",
                            f"Your opponent's {piece_name} on {sq_name} had no defenders — "
                            f"you could have captured it for free.",
                        )
        except Exception:
            pass

    # Most common blunder type — check whether our move created a loose piece.
    try:
        board_after = board.copy()
        board_after.push(played)
        hanging_sq = _find_hanging_square(board_after, mover)
        if hanging_sq is not None:
            piece = board_after.piece_at(hanging_sq)
            piece_name = _PIECE_NAMES[piece.piece_type]
            sq_name = chess.square_name(hanging_sq)
            return (
                "hanging_piece",
                f"After your move, your {piece_name} on {sq_name} was left with no defenders — "
                f"your opponent can capture it for free.",
            )
    except Exception:
        pass

    # Pawn-specific structural checks only apply when a pawn was actually the piece moved.
    piece = board.piece_at(played.from_square)
    if piece is not None and piece.piece_type == chess.PAWN:
        try:
            if _weakens_king_shield(board, played, mover):
                return (
                    "king_safety",
                    "You pushed a pawn from directly in front of your castled king, "
                    "weakening your king's defensive cover.",
                )
            if _is_pawn_overextension(board, played, mover):
                sq_name = chess.square_name(played.to_square)
                return (
                    "pawn_overextension",
                    f"You pushed a pawn aggressively to {sq_name} on the same side as your "
                    f"castled king — over-extended pawns become targets and strip your king's cover.",
                )
        except Exception:
            pass

    return _severity_from_loss(loss), _fallback_description(_severity_from_loss(loss), loss)


def _fallback_description(severity: str, loss: float) -> str:
    pawns = round(loss / 100, 1)
    if severity == "blunder":
        return (
            f"A significant error — this gave away roughly {pawns} pawns worth of advantage. "
            f"The position was recoverable before this move."
        )
    if severity == "mistake":
        return (
            f"A moderate error that handed your opponent some advantage "
            f"(about {pawns} pawns worth)."
        )
    return "A small imprecision that slightly weakened your position."


def _find_hanging_square(board: chess.Board, color: chess.Color) -> chess.Square | None:
    opponent = not color
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color or piece.piece_type == chess.KING:
            continue
        if board.is_attacked_by(opponent, sq) and not board.is_attacked_by(color, sq):
            return sq
    return None


def _weakens_king_shield(board: chess.Board, move: chess.Move, color: chess.Color) -> bool:
    king_sq = board.king(color)
    if king_sq is None:
        return False
    king_file = chess.square_file(king_sq)
    king_rank = chess.square_rank(king_sq)
    from_file = chess.square_file(move.from_square)
    from_rank = chess.square_rank(move.from_square)
    if abs(from_file - king_file) > 1:
        return False
    shield_rank = king_rank + 1 if color == chess.WHITE else king_rank - 1
    return from_rank == shield_rank


def _is_pawn_overextension(board: chess.Board, move: chess.Move, color: chess.Color) -> bool:
    to_file = chess.square_file(move.to_square)
    to_rank = chess.square_rank(move.to_square)
    if to_file < 4:  # queenside pawns are not flagged as kingside overextensions
        return False
    # Rank indices are 0–7 from white's back rank; rank 4 is the 5th rank for white.
    if color == chess.WHITE:
        if to_rank < 4:
            return False
    else:
        if to_rank > 3:
            return False
    king_sq = board.king(color)
    if king_sq is None:
        return False
    return chess.square_file(king_sq) >= 4


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

    return int(total), [
        {
            "category": row.category,
            "phase": row.phase,
            "occurrences": int(row.occurrences),
            "avg_eval_loss_cp": float(row.avg_eval_loss_cp or 0.0),
        }
        for row in rows
    ]


def _severity_from_loss(loss: float) -> str:
    if loss < 100:
        return "inaccuracy"
    if loss < 200:
        return "mistake"
    return "blunder"


def _phase_for_ply(ply: int) -> str:
    if ply <= 20:
        return "opening"
    if ply <= 60:
        return "middlegame"
    return "endgame"
