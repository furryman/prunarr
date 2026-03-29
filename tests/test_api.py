"""Tests for the Prunarr FastAPI endpoints."""

import sqlite3
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class TestRootEndpoint:
    async def test_root_returns_html(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Prunarr" in resp.text


class TestStatsEndpoint:
    async def test_stats_empty_db(self, client: AsyncClient):
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] == 0
        assert data["movies_count"] == 0
        assert data["shows_count"] == 0
        assert data["total_size"] == 0
        assert data["reclaimable_size"] == 0


class TestMoviesEndpoint:
    async def test_movies_empty(self, client: AsyncClient):
        resp = await client.get("/api/movies")
        assert resp.status_code == 200
        assert resp.json() == []


class TestShowsEndpoint:
    async def test_shows_empty(self, client: AsyncClient):
        resp = await client.get("/api/shows")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPosterProxy:
    async def test_poster_proxy_blocked_host(self, client: AsyncClient):
        resp = await client.get("/api/poster", params={"url": "https://evil.example.com/hack.jpg"})
        assert resp.status_code == 403

    async def test_poster_proxy_missing_url(self, client: AsyncClient):
        resp = await client.get("/api/poster")
        assert resp.status_code == 422


class TestDeleteEndpoints:
    async def test_delete_movie_mocked(self, client: AsyncClient, test_db: str):
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO media (radarr_id, title, media_type, size_bytes) VALUES (?, ?, ?, ?)",
            (101, "Test Movie", "movie", 1000),
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", ("radarr_url", "http://radarr:7878")
        )
        conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", ("radarr_api_key", "test-key"))
        conn.commit()
        conn.close()

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        with patch("app.main.httpx.AsyncClient") as mock_cls:
            mi = AsyncMock()
            mi.__aenter__ = AsyncMock(return_value=mi)
            mi.__aexit__ = AsyncMock(return_value=False)
            mi.delete = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mi
            resp = await client.delete("/api/movies/101")
            assert resp.status_code == 200

    async def test_delete_show_mocked(self, client: AsyncClient, test_db: str):
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO media (sonarr_id, title, media_type, size_bytes) VALUES (?, ?, ?, ?)",
            (201, "Test Show", "show", 2000),
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", ("sonarr_url", "http://sonarr:8989")
        )
        conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", ("sonarr_api_key", "test-key"))
        conn.commit()
        conn.close()

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        with patch("app.main.httpx.AsyncClient") as mock_cls:
            mi = AsyncMock()
            mi.__aenter__ = AsyncMock(return_value=mi)
            mi.__aexit__ = AsyncMock(return_value=False)
            mi.delete = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mi
            resp = await client.delete("/api/shows/201")
            assert resp.status_code == 200


class TestSettingsEndpoints:
    async def test_get_settings(self, client: AsyncClient):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "settings" in data
        assert "schema" in data

    async def test_save_and_read(self, client: AsyncClient):
        resp = await client.post("/api/settings", json={"app_name": "TestApp"})
        assert resp.status_code == 200
        resp2 = await client.get("/api/settings")
        assert resp2.json()["settings"]["app_name"] == "TestApp"

    async def test_settings_page(self, client: AsyncClient):
        resp = await client.get("/settings")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestUISmoke:
    async def test_root_has_key_elements(self, client: AsyncClient):
        resp = await client.get("/")
        text = resp.text.lower()
        assert "scan" in text
        assert "movie" in text or "movies" in text

    async def test_settings_has_form_elements(self, client: AsyncClient):
        resp = await client.get("/settings")
        assert resp.status_code == 200


class TestSettingsSecurity:
    """Test security aspects of the settings endpoints."""

    async def test_api_keys_masked_in_response(self, client: AsyncClient, test_db: str):
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ("radarr_api_key", "abcdef1234567890"),
        )
        conn.commit()
        conn.close()

        resp = await client.get("/api/settings")
        data = resp.json()
        key_val = data["settings"]["radarr_api_key"]
        assert key_val.endswith("7890")
        assert "********" in key_val
        assert "abcdef" not in key_val

    async def test_weight_validation_rejects_bad_sum(self, client: AsyncClient):
        resp = await client.post(
            "/api/settings",
            json={
                "weight_ratings": 50,
                "weight_engagement": 50,
                "weight_recency": 50,
                "weight_breadth": 10,
                "weight_continuing": 5,
            },
        )
        assert resp.status_code == 400
        assert "100" in resp.json()["detail"]

    async def test_weight_validation_accepts_valid_sum(self, client: AsyncClient):
        resp = await client.post(
            "/api/settings",
            json={
                "weight_ratings": 25,
                "weight_engagement": 35,
                "weight_recency": 20,
                "weight_breadth": 15,
                "weight_continuing": 5,
            },
        )
        assert resp.status_code == 200


class TestTestConnection:
    """Test the /api/settings/test-connection endpoint."""

    async def test_unknown_service_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/settings/test-connection",
            json={"service": "unknown", "url": "http://foo", "api_key": "bar"},
        )
        assert resp.status_code == 400

    async def test_missing_url_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/settings/test-connection",
            json={"service": "radarr", "url": "", "api_key": "bar"},
        )
        assert resp.status_code == 400

    async def test_cloud_metadata_blocked(self, client: AsyncClient):
        resp = await client.post(
            "/api/settings/test-connection",
            json={
                "service": "radarr",
                "url": "http://169.254.169.254/latest/meta-data",
                "api_key": "test",
            },
        )
        assert resp.status_code == 400
        assert "blocked" in resp.json()["detail"].lower()
