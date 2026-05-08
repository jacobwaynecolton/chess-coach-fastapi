from fastapi import FastAPI

from app.api.analysis import router as analysis_router
from app.api.games import router as games_router
from app.api.patterns import router as patterns_router
from app.core.config import DATA_DIR, UPLOADS_DIR
from app.core.database import Base, engine
from app.models.analysis import MoveAnalysis  # noqa: F401
from app.models.game import Game  # noqa: F401
from app.models.mistake_event import MistakeEvent  # noqa: F401

app = FastAPI(title="Chess Coach AI")


@app.on_event("startup")
def on_startup() -> None:
    # Ensure local data folders + tables exist before serving requests.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(games_router)
app.include_router(analysis_router)
app.include_router(patterns_router)
