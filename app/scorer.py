"""Scoring and recommendation engine for Prunarr.

Evaluates media items based on ratings, watch engagement, recency,
user breadth, and series status to produce a keep/delete recommendation.
"""

import math
from datetime import datetime, timezone
from typing import Optional

# Recommendation tier constants
STRONG_DELETE = "STRONG_DELETE"
DELETE = "DELETE"
CONSIDER = "CONSIDER"
KEEP = "KEEP"
STRONG_KEEP = "STRONG_KEEP"

TIER_ORDER = [STRONG_DELETE, DELETE, CONSIDER, KEEP, STRONG_KEEP]


def format_size(size_bytes: int) -> str:
    """Format a byte count into a human-readable string (e.g. '24.1 GB', '156 MB')."""
    if size_bytes <= 0:
        return "0 B"
    if size_bytes < 1000:
        return f"{size_bytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size_bytes = size_bytes / 1000.0
        if size_bytes < 1000.0 or unit == "TB":
            if size_bytes >= 100:
                return f"{size_bytes:.0f} {unit}"
            if size_bytes >= 10:
                return f"{size_bytes:.1f} {unit}"
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.1f} TB"


def _score_ratings(
    rt_score: Optional[int],
    metacritic: Optional[int],
    imdb_score: Optional[float],
) -> tuple[float, str]:
    """Compute the rating factor (0-30 points).

    Averages all available ratings normalized to 0-1, then scales to 30.
    Returns (points, description string).
    """
    normalized = []
    parts = []

    if rt_score is not None:
        normalized.append(rt_score / 100.0)
        parts.append(f"RT: {rt_score}%")
    if metacritic is not None:
        normalized.append(metacritic / 100.0)
        parts.append(f"MC: {metacritic}")
    if imdb_score is not None:
        normalized.append(imdb_score / 10.0)
        parts.append(f"IMDB: {imdb_score}")

    if not normalized:
        return 15.0, "no ratings available"

    avg = sum(normalized) / len(normalized)
    points = avg * 30.0

    rating_str = ", ".join(parts)
    if avg >= 0.75:
        quality = "excellent"
    elif avg >= 0.6:
        quality = "good"
    elif avg >= 0.4:
        quality = "mixed"
    else:
        quality = "poor"

    return points, f"{quality} ratings ({rating_str})"


def _score_engagement(play_count: int) -> tuple[float, str]:
    """Compute the watch engagement factor (0-35 points) using a log scale."""
    if play_count <= 0:
        return 0.0, "never watched"

    if play_count <= 5:
        # Linear interpolation from 5 to 15 over 1-5 plays
        points = 5.0 + (play_count - 1) * (10.0 / 4.0)
    elif play_count <= 20:
        # Linear interpolation from 15 to 25 over 6-20 plays
        points = 15.0 + (play_count - 6) * (10.0 / 14.0)
    elif play_count <= 100:
        # Log scale from 25 to 30 over 21-100 plays
        ratio = math.log(play_count - 19) / math.log(81)  # log(1)/log(81)=0, log(81)/log(81)=1
        points = 25.0 + ratio * 5.0
    else:
        # Log scale from 30 to 35 for 101+ plays
        # Cap at a reasonable high value to approach but not exceed 35
        ratio = min(math.log(play_count - 99) / math.log(1000), 1.0)
        points = 30.0 + ratio * 5.0

    desc = f"{play_count} plays"
    return points, desc


def _score_recency(last_played_ts: Optional[int]) -> tuple[float, str]:
    """Compute the recency factor (0-20 points) based on last played timestamp.

    Uses discrete values: today=20, <=30d=18, <=90d=15, <=180d=12,
    <=365d=8, <=730d=4, >730d=2, never=0.
    """
    if last_played_ts is None or last_played_ts == 0:
        return 0.0, "never played"

    now = datetime.now(timezone.utc)
    last_played = datetime.fromtimestamp(last_played_ts, tz=timezone.utc)
    days_ago = max(0.0, (now - last_played).total_seconds() / 86400.0)

    if days_ago < 1:
        points = 20.0
        desc = "today"
    elif days_ago <= 30:
        points = 18.0
        desc = f"{int(days_ago)}d ago"
    elif days_ago <= 90:
        points = 15.0
        desc = f"{int(days_ago)}d ago"
    elif days_ago <= 180:
        points = 12.0
        desc = f"{int(days_ago)}d ago"
    elif days_ago <= 365:
        points = 8.0
        desc = f"{int(days_ago)}d ago"
    elif days_ago <= 730:
        points = 4.0
        desc = f"{int(days_ago / 30)}mo ago"
    else:
        points = 2.0
        desc = f"{int(days_ago / 365)}yr ago"

    return points, f"last {desc}"


def _score_user_breadth(unique_users: int) -> tuple[float, str]:
    """Compute the user breadth factor (0-10 points)."""
    if unique_users <= 0:
        return 0.0, "0 users"
    elif unique_users == 1:
        return 4.0, "1 user"
    elif unique_users <= 3:
        return 7.0, f"{unique_users} users"
    else:
        return 10.0, f"{unique_users} users"


def _get_tier(score: float) -> str:
    """Map a numeric score (0-100) to a recommendation tier."""
    if score <= 20:
        return STRONG_DELETE
    elif score <= 40:
        return DELETE
    elif score <= 60:
        return CONSIDER
    elif score <= 80:
        return KEEP
    else:
        return STRONG_KEEP


def score_media(
    rt_score: Optional[int] = None,
    metacritic: Optional[int] = None,
    imdb_score: Optional[float] = None,
    play_count: int = 0,
    last_played_ts: Optional[int] = None,
    size_bytes: int = 0,
    unique_users: int = 0,
    is_continuing: bool = False,
    total_episodes: int = 0,
) -> dict:
    """Score a media item and return a recommendation.

    Args:
        rt_score: Rotten Tomatoes score (0-100), or None if unavailable.
        metacritic: Metacritic score (0-100), or None if unavailable.
        imdb_score: IMDB score (0-10), or None if unavailable.
        play_count: Total number of times the media has been played.
        last_played_ts: Unix timestamp of the last play, or None/0 if never.
        size_bytes: Size of the media on disk in bytes.
        unique_users: Number of distinct users who have watched.
        is_continuing: Whether the series is still airing new episodes.
        total_episodes: Total number of episodes (for series).

    Returns:
        dict with keys: score, tier, reason, factors.
    """
    rating_pts, rating_desc = _score_ratings(rt_score, metacritic, imdb_score)
    engagement_pts, engagement_desc = _score_engagement(play_count)
    recency_pts, recency_desc = _score_recency(last_played_ts)
    breadth_pts, breadth_desc = _score_user_breadth(unique_users)

    # Continuing series bonus: 5 points if still airing and watched at least once
    continuing_pts = 5.0 if (is_continuing and play_count > 0) else 0.0
    continuing_desc = "continuing series bonus" if continuing_pts > 0 else ""

    total = rating_pts + engagement_pts + recency_pts + breadth_pts + continuing_pts
    total = max(0.0, min(100.0, total))

    tier = _get_tier(total)

    # Build human-readable reason
    reason_parts = []

    # Lead with engagement context
    if play_count == 0:
        reason_parts.append("Never watched")
    else:
        recency_bit = f", {recency_desc}" if recency_desc != "never played" else ""
        users_bit = f", {breadth_desc}" if unique_users > 0 else ""
        reason_parts.append(f"Actively watched ({engagement_desc}{users_bit}{recency_bit})")

    # Add rating context
    reason_parts.append(rating_desc)

    # Add size context for delete-leaning items
    if size_bytes > 0 and tier in (STRONG_DELETE, DELETE, CONSIDER):
        reason_parts.append(f"{format_size(size_bytes)} reclaimable")

    # Add continuing series note
    if is_continuing and play_count > 0:
        reason_parts.append("still airing")

    reason = ", ".join(reason_parts)

    factors = {
        "rating": {"points": round(rating_pts, 1), "max": 30, "detail": rating_desc},
        "engagement": {"points": round(engagement_pts, 1), "max": 35, "detail": engagement_desc},
        "recency": {"points": round(recency_pts, 1), "max": 20, "detail": recency_desc},
        "user_breadth": {"points": round(breadth_pts, 1), "max": 10, "detail": breadth_desc},
        "continuing_bonus": {"points": round(continuing_pts, 1), "max": 5, "detail": continuing_desc},
    }

    return {
        "score": int(round(total)),
        "tier": tier,
        "reason": reason,
        "factors": factors,
    }
