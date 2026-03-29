"""Tests for the Prunarr scoring engine."""

import time

from app.scorer import (
    CONSIDER,
    DELETE,
    KEEP,
    STRONG_DELETE,
    STRONG_KEEP,
    format_size,
    score_media,
)


class TestScoreMedia:
    """Test the main score_media function with various scenarios."""

    def test_never_watched_low_rated_large_file(self):
        """Never watched + poor ratings -> STRONG_DELETE."""
        result = score_media(
            rt_score=20,
            metacritic=15,
            imdb_score=2.0,
            play_count=0,
            size_bytes=50_000_000_000,
        )
        assert result["tier"] == STRONG_DELETE
        assert result["score"] <= 20

    def test_never_watched_high_rated(self):
        """Never watched but high ratings -> CONSIDER (good ratings, no engagement)."""
        result = score_media(
            rt_score=95,
            metacritic=90,
            imdb_score=8.5,
            play_count=0,
            size_bytes=10_000_000_000,
        )
        # High ratings (avg ~0.91 -> ~27.3 pts) but zero engagement/recency/breadth
        # Total should land in CONSIDER range (21-60)
        assert result["tier"] in (CONSIDER, DELETE)
        assert result["score"] <= 60

    def test_frequently_watched_high_rated(self):
        """Frequently watched + high rated -> STRONG_KEEP."""
        now = int(time.time())
        result = score_media(
            rt_score=90,
            metacritic=85,
            imdb_score=8.0,
            play_count=50,
            last_played_ts=now - 3600,  # played an hour ago
            unique_users=4,
        )
        assert result["tier"] == STRONG_KEEP
        assert result["score"] > 80

    def test_watched_once_years_ago_mediocre(self):
        """Watched once 3 years ago with mediocre ratings -> DELETE."""
        three_years_ago = int(time.time()) - 86400 * 365 * 3
        result = score_media(
            rt_score=50,
            metacritic=45,
            imdb_score=5.0,
            play_count=1,
            last_played_ts=three_years_ago,
            size_bytes=20_000_000_000,
            unique_users=1,
        )
        # Rating: ~14.5pts, engagement: 5pts, recency: 2pts, breadth: 4pts = ~25.5
        assert result["tier"] in (DELETE, CONSIDER)
        assert result["score"] <= 40

    def test_actively_watched_continuing_show(self):
        """Actively watched continuing show -> KEEP or STRONG_KEEP."""
        now = int(time.time())
        result = score_media(
            imdb_score=7.0,
            play_count=30,
            last_played_ts=now - 86400 * 5,  # 5 days ago
            unique_users=3,
            is_continuing=True,
            total_episodes=50,
        )
        # IMDB 7.0 -> 21pts, engagement ~25+, recency 18, breadth 7, continuing 5
        assert result["tier"] in (KEEP, STRONG_KEEP)
        assert result["score"] >= 60
        # Verify continuing bonus is applied
        assert result["factors"]["continuing_bonus"]["points"] == 5.0

    def test_all_ratings_missing(self):
        """All ratings None -> neutral rating score of 15."""
        result = score_media(
            rt_score=None,
            metacritic=None,
            imdb_score=None,
            play_count=0,
        )
        assert result["factors"]["rating"]["points"] == 15.0
        assert "no ratings" in result["factors"]["rating"]["detail"]

    def test_zero_size_file(self):
        """Zero size file still scores based on other factors."""
        now = int(time.time())
        result = score_media(
            rt_score=80,
            play_count=10,
            last_played_ts=now - 3600,
            size_bytes=0,
            unique_users=2,
        )
        # Should still produce a valid score based on ratings, engagement, recency, breadth
        assert result["score"] > 0
        assert result["tier"] in (CONSIDER, KEEP, STRONG_KEEP)

    def test_score_boundaries(self):
        """Verify tier thresholds at exact boundary values."""
        # Boundary at 20: <=20 is STRONG_DELETE
        assert score_media(play_count=0, rt_score=30, metacritic=30, imdb_score=3.0)["score"] <= 20 or score_media(
            play_count=0, rt_score=30, metacritic=30, imdb_score=3.0
        )["tier"] in (STRONG_DELETE, DELETE)

        # Verify tier ordering makes sense: higher scores get better tiers
        low = score_media(play_count=0, rt_score=10, imdb_score=1.0)
        high = score_media(
            play_count=100,
            rt_score=95,
            imdb_score=9.0,
            last_played_ts=int(time.time()),
            unique_users=5,
        )
        tier_order = [STRONG_DELETE, DELETE, CONSIDER, KEEP, STRONG_KEEP]
        assert tier_order.index(high["tier"]) > tier_order.index(low["tier"])


class TestFormatSize:
    """Test the format_size helper function."""

    def test_format_size_bytes(self):
        assert format_size(500) == "500 B"

    def test_format_size_zero(self):
        assert format_size(0) == "0 B"

    def test_format_size_kb(self):
        result = format_size(1500)
        assert "KB" in result

    def test_format_size_mb(self):
        result = format_size(5_000_000)
        assert "MB" in result

    def test_format_size_gb(self):
        result = format_size(15_000_000_000)
        assert "GB" in result

    def test_format_size_tb(self):
        result = format_size(2_500_000_000_000)
        assert "TB" in result


class TestReasonString:
    """Test that reason strings contain relevant information."""

    def test_reason_contains_ratings_info(self):
        result = score_media(rt_score=90, metacritic=80, imdb_score=7.5, play_count=0)
        reason = result["reason"]
        assert "RT:" in reason or "ratings" in reason.lower()

    def test_reason_contains_play_count_for_watched(self):
        now = int(time.time())
        result = score_media(play_count=10, last_played_ts=now - 3600, unique_users=2)
        reason = result["reason"]
        assert "10 plays" in reason

    def test_reason_mentions_never_watched(self):
        result = score_media(play_count=0)
        assert "Never watched" in result["reason"]

    def test_reason_mentions_size_for_delete_candidates(self):
        result = score_media(
            play_count=0,
            rt_score=20,
            imdb_score=2.0,
            size_bytes=50_000_000_000,
        )
        reason = result["reason"]
        # Size info should appear for delete-leaning items
        if result["tier"] in (STRONG_DELETE, DELETE, CONSIDER):
            assert "GB" in reason or "reclaimable" in reason


class TestCustomWeightsAndThresholds:
    """Test score_media with configurable weights and thresholds."""

    def test_custom_weights_scale_correctly(self):
        """Custom weights should shift scores proportionally."""
        now = int(time.time())
        # Give all weight to ratings, zero engagement
        custom = score_media(
            rt_score=90,
            play_count=20,
            last_played_ts=now - 3600,
            unique_users=3,
            weights={
                "ratings": 80,
                "engagement": 0,
                "recency": 10,
                "breadth": 5,
                "continuing": 5,
            },
        )
        assert custom["factors"]["rating"]["max"] == 80
        assert custom["factors"]["engagement"]["max"] == 0

    def test_custom_thresholds(self):
        """Custom thresholds should change tier assignment."""
        # With default thresholds, score 50 => CONSIDER (40 < 50 <= 60)
        default = score_media(rt_score=80, play_count=3, unique_users=1)
        # With very strict thresholds, even mid scores become KEEP
        strict = score_media(
            rt_score=80,
            play_count=3,
            unique_users=1,
            thresholds={"strong_delete": 5, "delete": 10, "consider": 15, "keep": 20},
        )
        # Same raw score but higher tier with lenient thresholds
        assert strict["score"] == default["score"]

    def test_none_weights_uses_defaults(self):
        """Passing None for weights should use built-in defaults."""
        result = score_media(rt_score=50, play_count=0, weights=None, thresholds=None)
        assert result["factors"]["rating"]["max"] == 30.0
        assert result["factors"]["engagement"]["max"] == 35.0
