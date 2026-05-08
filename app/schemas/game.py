from pydantic import BaseModel


class GameOut(BaseModel):
    id: int
    source_file: str
    event: str | None = None
    site: str | None = None
    date: str | None = None
    white: str | None = None
    black: str | None = None
    result: str | None = None
    eco: str | None = None
    time_control: str | None = None
    moves_san: str

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    saved_games: int
    source_file: str
