from sqlalchemy import Column, Float, ForeignKey, Integer, String

from app.core.database import Base


class MistakeEvent(Base):
    __tablename__ = "mistake_events"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    analysis_id = Column(
        Integer, ForeignKey("move_analyses.id"), nullable=False, index=True
    )
    ply = Column(Integer, nullable=False)
    side_to_move = Column(String, nullable=False)
    phase = Column(String, nullable=False)
    category = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    eval_loss_cp = Column(Float, nullable=True)
