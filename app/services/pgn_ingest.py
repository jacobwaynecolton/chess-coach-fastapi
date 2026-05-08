from io import StringIO

import chess.pgn
from sqlalchemy.orm import Session

from app.models.game import Game


def ingest_pgn_text(db: Session, pgn_text: str, source_file: str) -> int:
    # `read_game` consumes one game at a time from this stream.
    stream = StringIO(pgn_text)
    saved = 0

    while True:
        parsed = chess.pgn.read_game(stream)
        if parsed is None:
            break

        # Keep a SAN move sequence so the game is easy to inspect quickly.
        moves_san = _build_san_line(parsed)

        game = Game(
            source_file=source_file,
            event=parsed.headers.get("Event"),
            site=parsed.headers.get("Site"),
            date=parsed.headers.get("Date"),
            white=parsed.headers.get("White"),
            black=parsed.headers.get("Black"),
            result=parsed.headers.get("Result"),
            eco=parsed.headers.get("ECO"),
            time_control=parsed.headers.get("TimeControl"),
            moves_san=moves_san,
            pgn_text=str(parsed),
        )

        db.add(game)
        saved += 1

    # Single commit is faster than committing each game row.
    db.commit()
    return saved


def _build_san_line(game: chess.pgn.Game) -> str:
    board = game.board()
    san_moves: list[str] = []
    for move in game.mainline_moves():
        # SAN must be computed before pushing the move.
        san_moves.append(board.san(move))
        board.push(move)
    return " ".join(san_moves)
