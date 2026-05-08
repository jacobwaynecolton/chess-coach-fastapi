import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch_chesscom_games_as_pgn(username: str) -> tuple[str, int]:
    normalized = username.strip().lower()
    if not normalized:
        return "", 0

    archives_url = f"https://api.chess.com/pub/player/{normalized}/games/archives"
    archives_payload = _fetch_json(archives_url)
    archive_urls: list[str] = archives_payload.get("archives", [])

    pgn_chunks: list[str] = []
    games_count = 0
    for url in archive_urls:
        monthly_payload = _fetch_json(url)
        for game in monthly_payload.get("games", []):
            pgn = game.get("pgn")
            if pgn:
                pgn_chunks.append(pgn.strip())
                games_count += 1

    return "\n\n".join(pgn_chunks), games_count


def _fetch_json(url: str) -> dict:
    request = Request(
        url=url,
        headers={
            "User-Agent": "chess-coach-ai/1.0 (+https://github.com/jacobwaynecolton/chess-coach-fastapi)"
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Chess.com API returned {exc.code} for URL: {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Chess.com API: {exc.reason}") from exc
