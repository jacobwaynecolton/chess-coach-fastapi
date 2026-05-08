from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "chess_coach.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "stockfish")
