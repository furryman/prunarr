"""Pydantic models for Prunarr API responses."""

from typing import Any

from pydantic import BaseModel


class MediaItem(BaseModel):
    id: int
    title: str
    year: int | None = None
    size_bytes: int = 0
    size_human: str = ""
    poster_url: str | None = None
    rt_score: int | None = None
    metacritic: int | None = None
    imdb_score: float | None = None
    play_count: int = 0
    last_played: int | None = None
    last_played_human: str = ""
    unique_users: int = 0
    genres: str = ""
    status: str = ""
    media_type: str = "movie"
    episodes: int = 0
    score: float = 0.0
    tier: str = ""
    reason: str = ""
    recommendation: dict[str, Any] | None = None


class StatsResponse(BaseModel):
    total_size: int = 0
    total_size_human: str = ""
    total_items: int = 0
    movies_count: int = 0
    shows_count: int = 0
    reclaimable_size: int = 0
    reclaimable_size_human: str = ""
    tier_counts: dict[str, int] = {}
