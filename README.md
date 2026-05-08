# Chess Coach AI

Python + FastAPI backend for ingesting your chess games, analyzing them with Stockfish, and finding recurring mistake patterns.

## Work phases

1. Phase 1 (current): project setup + PGN ingestion + game storage.
2. Phase 2: Stockfish move-by-move analysis pipeline.
3. Phase 3: mistake/event tagging from engine + position features.
4. Phase 4: recurring pattern aggregation and recommendation endpoints.
5. Phase 5 (optional): ML layer for personalized prioritization and predictions.

## Phase 1 scope

- Upload `.pgn` files through API.
- Parse all games with `python-chess`.
- Store normalized game metadata and SAN move text in SQLite.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open:

- `http://127.0.0.1:8000/docs`
- `POST /games/upload`
- `GET /games`
