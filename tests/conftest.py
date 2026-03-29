"""Shared fixtures for Prunarr tests."""

import sqlite3
import tempfile
import time
from collections.abc import AsyncIterator
from unittest.mock import patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def sample_movie_data() -> dict:
    """Sample movie data as returned by Radarr fetch processing."""
    return {
        "radarr_id": 101,
        "title": "Test Movie",
        "year": 2020,
        "size_bytes": 15_000_000_000,
        "poster_url": "https://image.tmdb.org/t/p/poster.jpg",
        "rt_score": 85,
        "metacritic": 72,
        "imdb_score": 7.5,
        "genres": "Action,Thriller",
        "has_file": True,
        "media_type": "movie",
    }


@pytest.fixture
def sample_show_data() -> dict:
    """Sample show data as returned by Sonarr fetch processing."""
    return {
        "sonarr_id": 201,
        "title": "Test Show",
        "year": 2019,
        "size_bytes": 45_000_000_000,
        "poster_url": "https://image.tmdb.org/t/p/show_poster.jpg",
        "imdb_score": 8.2,
        "genres": "Drama,Sci-Fi",
        "status": "continuing",
        "episodes": 30,
        "media_type": "show",
    }


@pytest.fixture
def sample_tautulli_history() -> dict:
    """Sample Tautulli history map keyed by lowercase title."""
    now = int(time.time())
    return {
        "test movie": {
            "play_count": 5,
            "last_played": now - 86400 * 7,
            "unique_users": 2,
        },
        "test show": {
            "play_count": 25,
            "last_played": now - 86400 * 2,
            "unique_users": 3,
        },
    }


@pytest.fixture
async def test_db() -> AsyncIterator[str]:
    """Create a temporary SQLite database with full schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Create both tables (media + app_settings)
    conn = sqlite3.connect(db_path)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radarr_id INTEGER, sonarr_id INTEGER,
        title TEXT NOT NULL, year INTEGER,
        size_bytes INTEGER DEFAULT 0, poster_url TEXT,
        rt_score INTEGER, metacritic INTEGER, imdb_score REAL,
        play_count INTEGER DEFAULT 0, last_played INTEGER,
        unique_users INTEGER DEFAULT 0, genres TEXT DEFAULT '',
        status TEXT DEFAULT '', media_type TEXT NOT NULL DEFAULT 'movie',
        episodes INTEGER DEFAULT 0, score REAL DEFAULT 0,
        tier TEXT DEFAULT '', reason TEXT DEFAULT '',
        last_scan INTEGER DEFAULT 0
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

    yield db_path


@pytest.fixture
async def client(test_db: str) -> AsyncIterator[AsyncClient]:
    """Create an async test client with all DB paths patched."""
    with (
        patch("app.main.DB_PATH", test_db),
        patch("app.config.settings.DB_PATH", test_db),
    ):
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
