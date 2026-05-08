from sqlalchemy import Column, Float, ForeignKey, Integer, String

from app.core.database import Base


class MoveAnalysis(Base):
    __tablename__ = "move_analyses"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    ply = Column(Integer, nullable=False)
    played_move_uci = Column(String, nullable=False)
    best_move_uci = Column(String, nullable=True)
    eval_cp_before = Column(Float, nullable=True)
    eval_cp_after = Column(Float, nullable=True)
    eval_loss_cp = Column(Float, nullable=True)
    side_to_move = Column(String, nullable=False)
