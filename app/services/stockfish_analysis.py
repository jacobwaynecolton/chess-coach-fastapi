from io import StringIO

import chess
import chess.engine
import chess.pgn
from sqlalchemy.orm import Session

from app.core.config import STOCKFISH_PATH
from app.models.analysis import MoveAnalysis
from app.models.game import Game


def analyze_game(db: Session, game: Game, depth: int = 12) -> int:
    parsed = chess.pgn.read_game(StringIO(game.pgn_text))
    if parsed is None:
        return 0

    # Re-run analysis from scratch for deterministic results.
    db.query(MoveAnalysis).filter(MoveAnalysis.game_id == game.id).delete()

    board = parsed.board()
    saved = 0

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        for ply, move in enumerate(parsed.mainline_moves(), start=1):
            side_to_move = "white" if board.turn == chess.WHITE else "black"
            before = _analyze_cp(engine=engine, board=board, depth=depth)
            best = _best_move_uci(engine=engine, board=board, depth=depth)

            board.push(move)
            after = _analyze_cp(engine=engine, board=board, depth=depth)

            eval_loss = None
            if before is not None and after is not None:
                # Flip after-score so both values are from the mover's perspective.
                normalized_after = -after
                eval_loss = before - normalized_after

            row = MoveAnalysis(
                game_id=game.id,
                ply=ply,
                played_move_uci=move.uci(),
                best_move_uci=best,
                eval_cp_before=before,
                eval_cp_after=after,
                eval_loss_cp=eval_loss,
                side_to_move=side_to_move,
            )
            db.add(row)
            saved += 1

    db.commit()
    return saved


def _analyze_cp(
    engine: chess.engine.SimpleEngine, board: chess.Board, depth: int
) -> float | None:
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    score = info.get("score")
    if score is None:
        return None

    pov = score.pov(board.turn)
    if pov.is_mate():
        # Keep mate scores finite for aggregation in Phase 3+.
        return 10000.0 if pov.mate() and pov.mate() > 0 else -10000.0

    cp = pov.score()
    return float(cp) if cp is not None else None


def _best_move_uci(
    engine: chess.engine.SimpleEngine, board: chess.Board, depth: int
) -> str | None:
    result = engine.play(board, chess.engine.Limit(depth=depth))
    return result.move.uci() if result.move else None
