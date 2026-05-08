import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "chess_coach.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

_stockfish_candidates = [
    os.getenv("STOCKFISH_PATH"),
    shutil.which("stockfish"),
    "/usr/bin/stockfish",
    "/usr/local/bin/stockfish",
]

STOCKFISH_PATH = next((p for p in _stockfish_candidates if p), "stockfish")
