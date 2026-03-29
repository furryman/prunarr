"""Prunarr - FastAPI backend for media library management."""

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import aiosqlite
import bcrypt
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    CONFIGURABLE_KEYS,
    _ensure_settings_table,
    get_all_settings,
    get_effective_service_config,
    get_scoring_weights,
    get_setting,
    get_tier_thresholds,
    save_settings,
    settings,
)
from app.models import StatsResponse
from app.scorer import DELETE, STRONG_DELETE, format_size, score_media

APP_DIR = Path(__file__).resolve().parent
DB_PATH = settings.DB_PATH

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    radarr_id INTEGER,
    sonarr_id INTEGER,
    title TEXT NOT NULL,
    year INTEGER,
    size_bytes INTEGER DEFAULT 0,
    poster_url TEXT,
    rt_score INTEGER,
    metacritic INTEGER,
    imdb_score REAL,
    play_count INTEGER DEFAULT 0,
    last_played INTEGER,
    unique_users INTEGER DEFAULT 0,
    genres TEXT DEFAULT '',
    status TEXT DEFAULT '',
    media_type TEXT NOT NULL DEFAULT 'movie',
    episodes INTEGER DEFAULT 0,
    score REAL DEFAULT 0,
    tier TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    last_scan INTEGER DEFAULT 0
);
"""


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize the SQLite database on startup."""
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE_SQL)
        await db.commit()
    _ensure_settings_table(DB_PATH)
    yield


app = FastAPI(title="Prunarr", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# ---------------------------------------------------------------------------
# Session-based authentication
# ---------------------------------------------------------------------------

# In-memory session store: maps session token -> expiry timestamp
_sessions: dict[str, float] = {}
_SESSION_TTL = 86400 * 7  # 7 days

# Routes that never require auth
_PUBLIC_PATHS: set[str] = {"/api/login", "/login", "/static"}


def _is_auth_required() -> bool:
    """Check whether authentication is enabled and a password is set."""
    auth_enabled = get_setting("auth_enabled")
    auth_password = get_setting("auth_password")
    return bool(auth_enabled and auth_password)


def _is_public_path(path: str) -> bool:
    """Return True if the path should be accessible without authentication."""
    if path.startswith("/static"):
        return True
    return path in _PUBLIC_PATHS


def _validate_session(token: str | None) -> bool:
    """Return True if the session token is valid and not expired."""
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None:
        return False
    if time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce session authentication when auth is enabled."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if _is_auth_required() and not _is_public_path(request.url.path):
            session_token = request.cookies.get("prunarr_session")
            if not _validate_session(session_token):
                # API requests get 401; browser requests get redirected to /login
                if request.url.path.startswith("/api/"):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Authentication required"},
                    )
                return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)


app.add_middleware(AuthMiddleware)


def _format_last_played(ts: int | None) -> str:
    """Format a unix timestamp into a human-readable relative time string."""
    if not ts or ts == 0:
        return "Never"
    now = time.time()
    diff = now - ts
    if diff < 86400:
        return "Today"
    days = int(diff / 86400)
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}yr ago"


def _extract_poster(images: list[dict[str, Any]]) -> str | None:
    """Extract poster URL from a Radarr/Sonarr images list."""
    for img in images:
        if img.get("coverType") == "poster":
            return img.get("remoteUrl") or img.get("url") or None
    return None


def _rating_or_none(value: int | float | None) -> int | float | None:
    """Treat zero ratings as None (unavailable)."""
    if value is None or value == 0:
        return None
    return value


async def _fetch_radarr_movies() -> list[dict[str, Any]]:
    """Fetch all movies from Radarr API."""
    svc = get_effective_service_config()
    radarr_url = svc["radarr_url"]
    radarr_api_key = svc["radarr_api_key"]
    if not radarr_url or not radarr_api_key:
        return []
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/movie",
            headers={"X-Api-Key": radarr_api_key},
        )
        resp.raise_for_status()
        movies: list[dict[str, Any]] = resp.json()

    results: list[dict[str, Any]] = []
    for m in movies:
        ratings = m.get("ratings", {})
        results.append(
            {
                "radarr_id": m.get("id"),
                "title": m.get("title", "Unknown"),
                "year": m.get("year"),
                "size_bytes": m.get("sizeOnDisk", 0) or 0,
                "poster_url": _extract_poster(m.get("images", [])),
                "rt_score": _rating_or_none(ratings.get("rottenTomatoes", {}).get("value")),
                "metacritic": _rating_or_none(ratings.get("metacritic", {}).get("value")),
                "imdb_score": _rating_or_none(ratings.get("imdb", {}).get("value")),
                "genres": ",".join(m.get("genres", [])),
                "has_file": m.get("hasFile", False),
                "media_type": "movie",
            }
        )
    return results


async def _fetch_sonarr_series() -> list[dict[str, Any]]:
    """Fetch all series from Sonarr API."""
    svc = get_effective_service_config()
    sonarr_url = svc["sonarr_url"]
    sonarr_api_key = svc["sonarr_api_key"]
    if not sonarr_url or not sonarr_api_key:
        return []
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{sonarr_url.rstrip('/')}/api/v3/series",
            headers={"X-Api-Key": sonarr_api_key},
        )
        resp.raise_for_status()
        series_list: list[dict[str, Any]] = resp.json()

    results: list[dict[str, Any]] = []
    for s in series_list:
        stats = s.get("statistics", {})
        ratings = s.get("ratings", {})
        results.append(
            {
                "sonarr_id": s.get("id"),
                "title": s.get("title", "Unknown"),
                "year": s.get("year"),
                "size_bytes": stats.get("sizeOnDisk", 0) or 0,
                "poster_url": _extract_poster(s.get("images", [])),
                "imdb_score": _rating_or_none(ratings.get("imdb", {}).get("value")),
                "genres": ",".join(s.get("genres", [])),
                "status": s.get("status", ""),
                "episodes": stats.get("episodeFileCount", 0) or 0,
                "media_type": "show",
            }
        )
    return results


async def _fetch_tautulli_history() -> dict[str, dict[str, Any]]:
    """Fetch all watch history from Tautulli, paginated.

    Returns a dict keyed by lowercase title with:
      {play_count, last_played, unique_users}
    """
    svc = get_effective_service_config()
    tautulli_url = svc["tautulli_url"]
    tautulli_api_key = svc["tautulli_api_key"]
    if not tautulli_url or not tautulli_api_key:
        return {}

    history_map: dict[str, dict[str, Any]] = {}
    start = 0
    page_size = 10000

    async with httpx.AsyncClient(timeout=120.0) as client:
        while True:
            resp = await client.get(
                f"{tautulli_url.rstrip('/')}/api/v2",
                params={
                    "apikey": tautulli_api_key,
                    "cmd": "get_history",
                    "length": page_size,
                    "start": start,
                },
            )
            resp.raise_for_status()
            data = resp.json().get("response", {}).get("data", {})
            records: list[dict[str, Any]] = data.get("data", [])

            if not records:
                break

            for rec in records:
                media_type = rec.get("media_type", "")
                if media_type == "movie":
                    key = (rec.get("title") or "").lower().strip()
                elif media_type in ("episode", "show"):
                    key = (rec.get("grandparent_title") or "").lower().strip()
                else:
                    continue

                if not key:
                    continue

                if key not in history_map:
                    history_map[key] = {
                        "play_count": 0,
                        "last_played": 0,
                        "unique_users": set(),
                    }

                history_map[key]["play_count"] += 1
                stopped = rec.get("stopped", 0) or rec.get("started", 0) or 0
                if stopped > history_map[key]["last_played"]:
                    history_map[key]["last_played"] = stopped
                user = rec.get("user")
                if user:
                    history_map[key]["unique_users"].add(user)

            total_count = data.get("recordsFiltered", data.get("recordsTotal", 0))
            start += page_size
            if start >= total_count:
                break

    # Convert sets to counts
    for entry in history_map.values():
        entry["unique_users"] = len(entry["unique_users"])

    return history_map


def _match_history(
    title: str,
    history_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Match a media title to Tautulli history using case-insensitive lookup.

    Falls back to fuzzy substring matching if exact match fails.
    """
    key = title.lower().strip()
    default: dict[str, Any] = {"play_count": 0, "last_played": 0, "unique_users": 0}

    # Exact match
    if key in history_map:
        return history_map[key]

    # Fuzzy: check if any history key is contained in title or vice versa
    for hkey, hval in history_map.items():
        if hkey in key or key in hkey:
            return hval

    return default


async def _insert_movie(
    db: aiosqlite.Connection,
    movie: dict[str, Any],
    history: dict[str, Any],
    now_ts: int,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> None:
    """Score and insert a movie into the database."""
    rec = score_media(
        rt_score=movie.get("rt_score"),
        metacritic=movie.get("metacritic"),
        imdb_score=movie.get("imdb_score"),
        play_count=history["play_count"],
        last_played_ts=history["last_played"] or None,
        size_bytes=movie["size_bytes"],
        unique_users=history["unique_users"],
        weights=weights,
        thresholds=thresholds,
    )
    await db.execute(
        """INSERT INTO media (radarr_id, title, year, size_bytes, poster_url,
           rt_score, metacritic, imdb_score, play_count, last_played,
           unique_users, genres, status, media_type, episodes, score, tier,
           reason, last_scan)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            movie["radarr_id"],
            movie["title"],
            movie.get("year"),
            movie["size_bytes"],
            movie.get("poster_url"),
            movie.get("rt_score"),
            movie.get("metacritic"),
            movie.get("imdb_score"),
            history["play_count"],
            history["last_played"] or None,
            history["unique_users"],
            movie.get("genres", ""),
            "",
            "movie",
            0,
            rec["score"],
            rec["tier"],
            rec["reason"],
            now_ts,
        ),
    )


async def _insert_show(
    db: aiosqlite.Connection,
    show: dict[str, Any],
    history: dict[str, Any],
    now_ts: int,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> None:
    """Score and insert a show into the database."""
    is_continuing = show.get("status", "").lower() == "continuing"
    rec = score_media(
        imdb_score=show.get("imdb_score"),
        play_count=history["play_count"],
        last_played_ts=history["last_played"] or None,
        size_bytes=show["size_bytes"],
        unique_users=history["unique_users"],
        is_continuing=is_continuing,
        total_episodes=show.get("episodes", 0),
        weights=weights,
        thresholds=thresholds,
    )
    await db.execute(
        """INSERT INTO media (sonarr_id, title, year, size_bytes, poster_url,
           rt_score, metacritic, imdb_score, play_count, last_played,
           unique_users, genres, status, media_type, episodes, score, tier,
           reason, last_scan)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            show["sonarr_id"],
            show["title"],
            show.get("year"),
            show["size_bytes"],
            show.get("poster_url"),
            None,
            None,
            show.get("imdb_score"),
            history["play_count"],
            history["last_played"] or None,
            history["unique_users"],
            show.get("genres", ""),
            show.get("status", ""),
            "show",
            show.get("episodes", 0),
            rec["score"],
            rec["tier"],
            rec["reason"],
            now_ts,
        ),
    )


@app.post("/api/scan")
async def scan_library() -> dict[str, str | int]:
    """Scan Radarr, Sonarr, and Tautulli, score media, and update the database."""
    logger = logging.getLogger("prunarr")

    # Fetch data from all sources concurrently; tolerate individual failures
    async def _safe_fetch_movies() -> list[dict[str, Any]]:
        try:
            return await _fetch_radarr_movies()
        except Exception as exc:
            logger.warning("Radarr fetch failed: %s", exc)
            return []

    async def _safe_fetch_shows() -> list[dict[str, Any]]:
        try:
            return await _fetch_sonarr_series()
        except Exception as exc:
            logger.warning("Sonarr fetch failed: %s", exc)
            return []

    async def _safe_fetch_history() -> dict[str, dict[str, Any]]:
        try:
            return await _fetch_tautulli_history()
        except Exception as exc:
            logger.warning("Tautulli fetch failed: %s", exc)
            return {}

    movies_data, shows_data, history_map = await asyncio.gather(
        _safe_fetch_movies(),
        _safe_fetch_shows(),
        _safe_fetch_history(),
    )

    now_ts = int(time.time())
    weights = get_scoring_weights()
    thresholds = get_tier_thresholds()

    async with aiosqlite.connect(DB_PATH) as db:
        # Clear old data for a clean scan
        await db.execute("DELETE FROM media")

        for movie in movies_data:
            history = _match_history(movie["title"], history_map)
            await _insert_movie(db, movie, history, now_ts, weights, thresholds)

        for show in shows_data:
            history = _match_history(show["title"], history_map)
            await _insert_show(db, show, history, now_ts, weights, thresholds)

        await db.commit()

    return {"status": "ok", "movies": len(movies_data), "shows": len(shows_data)}


_MEDIA_COLUMNS: list[str] = [
    "id",
    "radarr_id",
    "sonarr_id",
    "title",
    "year",
    "size_bytes",
    "poster_url",
    "rt_score",
    "metacritic",
    "imdb_score",
    "play_count",
    "last_played",
    "unique_users",
    "genres",
    "status",
    "media_type",
    "episodes",
    "score",
    "tier",
    "reason",
    "last_scan",
]


def _row_to_media_item(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a database row to a MediaItem dict."""
    d: dict[str, Any] = dict(zip(_MEDIA_COLUMNS, row, strict=False))
    d["size_human"] = format_size(d.get("size_bytes") or 0)
    d["last_played_human"] = _format_last_played(d.get("last_played"))
    return d


@app.get("/api/movies")
async def get_movies() -> list[dict[str, Any]]:
    """Return all movies sorted by size descending."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM media WHERE media_type = 'movie' ORDER BY size_bytes DESC")
        rows = await cursor.fetchall()
    return [_row_to_media_item(row) for row in rows]


@app.get("/api/shows")
async def get_shows() -> list[dict[str, Any]]:
    """Return all shows sorted by size descending."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM media WHERE media_type = 'show' ORDER BY size_bytes DESC")
        rows = await cursor.fetchall()
    return [_row_to_media_item(row) for row in rows]


@app.get("/api/stats")
async def get_stats() -> StatsResponse:
    """Return aggregate statistics from the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COALESCE(SUM(size_bytes), 0), COUNT(*) FROM media")
        total_size, total_items = await cursor.fetchone()  # type: ignore[misc]

        cursor = await db.execute("SELECT COUNT(*) FROM media WHERE media_type = 'movie'")
        movies_count: int = (await cursor.fetchone())[0]  # type: ignore[index]

        cursor = await db.execute("SELECT COUNT(*) FROM media WHERE media_type = 'show'")
        shows_count: int = (await cursor.fetchone())[0]  # type: ignore[index]

        cursor = await db.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM media WHERE tier IN (?, ?)",
            (DELETE, STRONG_DELETE),
        )
        reclaimable_size: int = (await cursor.fetchone())[0]  # type: ignore[index]

        cursor = await db.execute("SELECT tier, COUNT(*) FROM media GROUP BY tier")
        tier_rows = await cursor.fetchall()
        tier_counts: dict[str, int] = {row[0]: row[1] for row in tier_rows if row[0]}

    return StatsResponse(
        total_size=total_size,
        total_size_human=format_size(total_size),
        total_items=total_items,
        movies_count=movies_count,
        shows_count=shows_count,
        reclaimable_size=reclaimable_size,
        reclaimable_size_human=format_size(reclaimable_size),
        tier_counts=tier_counts,
    )


@app.delete("/api/movies/{radarr_id}")
async def delete_movie(radarr_id: int) -> dict[str, str | int]:
    """Delete a movie from Radarr and remove from local database."""
    svc = get_effective_service_config()
    radarr_url = svc["radarr_url"]
    radarr_api_key = svc["radarr_api_key"]
    if not radarr_url or not radarr_api_key:
        raise HTTPException(status_code=500, detail="Radarr not configured")

    delete_files = get_setting("delete_files_on_remove")
    add_exclusion = get_setting("add_exclusion_on_remove")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(
            f"{radarr_url.rstrip('/')}/api/v3/movie/{radarr_id}",
            headers={"X-Api-Key": radarr_api_key},
            params={
                "deleteFiles": str(delete_files).lower(),
                "addImportListExclusion": str(add_exclusion).lower(),
            },
        )
        if resp.status_code not in (200, 202, 204):
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Radarr delete failed: {resp.text}",
            )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM media WHERE radarr_id = ?", (radarr_id,))
        await db.commit()

    return {"status": "ok", "deleted": radarr_id}


@app.delete("/api/shows/{sonarr_id}")
async def delete_show(sonarr_id: int) -> dict[str, str | int]:
    """Delete a show from Sonarr and remove from local database."""
    svc = get_effective_service_config()
    sonarr_url = svc["sonarr_url"]
    sonarr_api_key = svc["sonarr_api_key"]
    if not sonarr_url or not sonarr_api_key:
        raise HTTPException(status_code=500, detail="Sonarr not configured")

    delete_files = get_setting("delete_files_on_remove")
    add_exclusion = get_setting("add_exclusion_on_remove")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(
            f"{sonarr_url.rstrip('/')}/api/v3/series/{sonarr_id}",
            headers={"X-Api-Key": sonarr_api_key},
            params={
                "deleteFiles": str(delete_files).lower(),
                "addImportListExclusion": str(add_exclusion).lower(),
            },
        )
        if resp.status_code not in (200, 202, 204):
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Sonarr delete failed: {resp.text}",
            )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM media WHERE sonarr_id = ?", (sonarr_id,))
        await db.commit()

    return {"status": "ok", "deleted": sonarr_id}


_ALLOWED_POSTER_HOSTS: set[str] = {
    "image.tmdb.org",
    "artworks.thetvdb.com",
    "www.thetvdb.com",
}


def _is_allowed_poster_url(url: str) -> bool:
    """Check if a poster URL points to an allowed host (SSRF prevention)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""

    # Allow configured Radarr/Sonarr hosts
    svc = get_effective_service_config()
    for service_url in (svc["radarr_url"], svc["sonarr_url"]):
        if service_url:
            service_host = urlparse(service_url).hostname
            if service_host and host == service_host:
                return True

    return host in _ALLOWED_POSTER_HOSTS


@app.get("/api/poster")
async def proxy_poster(
    url: Annotated[str, Query(description="Remote poster image URL to proxy")],
) -> Response:
    """Proxy poster images from Radarr/Sonarr to avoid CORS issues."""
    if not url:
        raise HTTPException(status_code=400, detail="Missing url parameter")

    if not _is_allowed_poster_url(url):
        raise HTTPException(status_code=403, detail="URL host not allowed")

    # Determine which API key to attach based on the URL
    svc = get_effective_service_config()
    headers: dict[str, str] = {}
    if svc["radarr_url"] and svc["radarr_url"].rstrip("/") in url:
        headers["X-Api-Key"] = svc["radarr_api_key"]
    elif svc["sonarr_url"] and svc["sonarr_url"].rstrip("/") in url:
        headers["X-Api-Key"] = svc["sonarr_api_key"]

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Failed to fetch poster") from exc


def _mask_secret(value: object, key: str) -> object:
    """Mask API keys and password hashes for UI display.

    Shows only the last 4 characters prefixed with asterisks.
    """
    meta = CONFIGURABLE_KEYS.get(key)
    if meta and meta.get("type") == "password":
        s = str(value) if value else ""
        if len(s) > 4:
            return "*" * 8 + s[-4:]
        if s:
            return "*" * 8
        return ""
    return value


@app.get("/api/settings")
async def api_get_settings() -> dict[str, Any]:
    """Return all current settings and schema metadata for the UI.

    API keys and password hashes are masked -- only the last 4 characters
    are exposed so the user can confirm which key is configured.
    """
    raw = get_all_settings()
    masked = {k: _mask_secret(v, k) for k, v in raw.items()}
    return {
        "settings": masked,
        "schema": CONFIGURABLE_KEYS,
    }


@app.post("/api/settings")
async def api_save_settings(request: Request) -> dict[str, Any]:
    """Save one or more settings. Validates scoring weights sum to 100."""
    body: dict[str, Any] = await request.json()

    # Validate scoring weights sum to 100 if any weight key is present
    weight_keys = [
        "weight_ratings",
        "weight_engagement",
        "weight_recency",
        "weight_breadth",
        "weight_continuing",
    ]
    incoming_weight_keys = [k for k in weight_keys if k in body]
    if incoming_weight_keys:
        # Merge incoming weights with current values for keys not being updated
        current = get_all_settings()
        total = 0
        for k in weight_keys:
            if k in body:
                total += int(body[k])
            else:
                total += int(current.get(k, CONFIGURABLE_KEYS[k]["default"]))
        if total != 100:
            raise HTTPException(
                status_code=400,
                detail=f"Scoring weights must sum to 100 (got {total})",
            )

    # Hash plaintext password before storing
    if "auth_password" in body and body["auth_password"]:
        plaintext = body["auth_password"]
        body["auth_password"] = bcrypt.hashpw(
            plaintext.encode(), bcrypt.gensalt()
        ).decode()

    save_settings(body)
    return {"status": "ok", "settings": get_all_settings()}


def _is_safe_service_url(url: str) -> bool:
    """Validate that a test-connection URL points to a plausible service host.

    Blocks cloud metadata endpoints and non-HTTP schemes to mitigate SSRF.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = (parsed.hostname or "").lower()
    # Block well-known cloud metadata endpoints
    blocked = {"169.254.169.254", "metadata.google.internal"}
    if hostname in blocked:
        return False
    return bool(hostname)


@app.post("/api/settings/test-connection")
async def api_test_connection(request: Request) -> dict[str, Any]:
    """Test connectivity to Radarr, Sonarr, or Tautulli."""
    body: dict[str, Any] = await request.json()
    service = body.get("service", "").lower()
    url = body.get("url", "").rstrip("/")
    api_key = body.get("api_key", "")

    if service not in ("radarr", "sonarr", "tautulli"):
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")
    if not url or not api_key:
        raise HTTPException(status_code=400, detail="URL and API key are required")
    if not _is_safe_service_url(url):
        raise HTTPException(status_code=400, detail="Invalid or blocked URL")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if service in ("radarr", "sonarr"):
                resp = await client.get(
                    f"{url}/api/v3/system/status",
                    headers={"X-Api-Key": api_key},
                )
            else:  # tautulli
                resp = await client.get(
                    f"{url}/api/v2",
                    params={"apikey": api_key, "cmd": "get_tautulli_info"},
                )
            resp.raise_for_status()
            return {"success": True, "message": f"Successfully connected to {service}"}
    except httpx.HTTPStatusError as exc:
        return {
            "success": False,
            "message": f"Connection failed: HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        return {"success": False, "message": f"Connection failed: {exc}"}


@app.post("/api/login")
async def api_login(request: Request) -> JSONResponse:
    """Authenticate with password, return session cookie."""
    body: dict[str, Any] = await request.json()
    password = body.get("password", "")

    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    stored_hash = get_setting("auth_password")
    if not stored_hash:
        raise HTTPException(status_code=400, detail="No password configured")

    if not bcrypt.checkpw(password.encode(), str(stored_hash).encode()):
        raise HTTPException(status_code=401, detail="Invalid password")

    # Create session
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _SESSION_TTL

    response = JSONResponse(content={"status": "ok"})
    response.set_cookie(
        key="prunarr_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=_SESSION_TTL,
    )
    return response


@app.post("/api/logout")
async def api_logout(request: Request) -> JSONResponse:
    """Invalidate the current session."""
    token = request.cookies.get("prunarr_session")
    if token:
        _sessions.pop(token, None)
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie("prunarr_session")
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Serve the login page."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    """Serve the settings page."""
    return templates.TemplateResponse(request, "settings.html")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main web interface."""
    return templates.TemplateResponse(request, "index.html")
