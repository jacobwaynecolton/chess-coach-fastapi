from sqlalchemy import Column, Integer, String, Text

from app.core.database import Base


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    source_file = Column(String, nullable=False)
    event = Column(String, nullable=True)
    site = Column(String, nullable=True)
    date = Column(String, nullable=True)
    white = Column(String, nullable=True)
    black = Column(String, nullable=True)
    result = Column(String, nullable=True)
    eco = Column(String, nullable=True)
    time_control = Column(String, nullable=True)
    moves_san = Column(Text, nullable=False)
    pgn_text = Column(Text, nullable=False)
