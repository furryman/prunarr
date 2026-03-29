"""Tests for the Prunarr FastAPI endpoints."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class TestRootEndpoint:
    """Test the main HTML page."""

    async def test_root_returns_html(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestStatsEndpoint:
    """Test the /api/stats endpoint."""

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
    """Test the /api/movies endpoint."""

    async def test_movies_empty(self, client: AsyncClient):
        resp = await client.get("/api/movies")
        assert resp.status_code == 200
        assert resp.json() == []


class TestShowsEndpoint:
    """Test the /api/shows endpoint."""

    async def test_shows_empty(self, client: AsyncClient):
        resp = await client.get("/api/shows")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPosterProxy:
    """Test the /api/poster endpoint."""

    async def test_poster_proxy_blocked_host(self, client: AsyncClient):
        resp = await client.get("/api/poster", params={"url": "https://evil.example.com/hack.jpg"})
        assert resp.status_code == 403

    async def test_poster_proxy_missing_url(self, client: AsyncClient):
        resp = await client.get("/api/poster")
        assert resp.status_code == 422


class TestDeleteMovie:
    """Test the DELETE /api/movies/{radarr_id} endpoint."""

    async def test_delete_movie_not_found(self, client: AsyncClient):
        """Deleting a non-existent movie should call Radarr and succeed (or handle gracefully)."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch("app.main.settings") as mock_settings:
            mock_settings.RADARR_URL = "http://radarr:7878"
            mock_settings.RADARR_API_KEY = "test-key"
            mock_settings.SONARR_URL = "http://sonarr:8989"
            mock_settings.SONARR_API_KEY = "test-key"
            mock_settings.TAUTULLI_URL = ""
            mock_settings.TAUTULLI_API_KEY = ""

            with patch("app.main.httpx.AsyncClient") as mock_client_cls:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client_instance.delete = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client_instance

                resp = await client.delete("/api/movies/999999")
                # Radarr returns 404, so the endpoint should raise an HTTPException
                assert resp.status_code == 404


class TestDeleteShow:
    """Test the DELETE /api/shows/{sonarr_id} endpoint."""

    async def test_delete_show_not_found(self, client: AsyncClient):
        """Deleting a non-existent show should call Sonarr and succeed (or handle gracefully)."""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch("app.main.settings") as mock_settings:
            mock_settings.RADARR_URL = "http://radarr:7878"
            mock_settings.RADARR_API_KEY = "test-key"
            mock_settings.SONARR_URL = "http://sonarr:8989"
            mock_settings.SONARR_API_KEY = "test-key"
            mock_settings.TAUTULLI_URL = ""
            mock_settings.TAUTULLI_API_KEY = ""

            with patch("app.main.httpx.AsyncClient") as mock_client_cls:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client_instance.delete = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client_instance

                resp = await client.delete("/api/shows/999999")
                # Sonarr returns 404, so the endpoint should raise an HTTPException
                assert resp.status_code == 404
