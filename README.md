# Prunarr

A media library pruning tool for the *arr ecosystem. Prunarr analyzes your Plex, Radarr, and Sonarr libraries — cross-referencing ratings, watch history, and file sizes — to recommend which media to **keep** and which to **delete**.

## Features

- **Smart Recommendations**: Weighted scoring algorithm using Rotten Tomatoes, Metacritic, IMDB ratings, Tautulli watch history, file sizes, and user engagement
- **5-Tier System**: STRONG DELETE, DELETE, CONSIDER, KEEP, STRONG KEEP — each with a human-readable explanation
- **Bulk Actions**: Select multiple items and delete them directly through Radarr/Sonarr APIs
- **Dark UI**: Clean, *arr-inspired dark theme with responsive card layout
- **Real-time Stats**: Dashboard showing total library size, reclaimable space, and tier breakdowns
- **Docker Native**: Single container, configurable via environment variables

## Scoring Algorithm

Each item is scored 0-100 based on:

| Factor | Weight | Description |
|--------|--------|-------------|
| Ratings | 30 pts | Average of RT, Metacritic, IMDB (normalized) |
| Watch Engagement | 35 pts | Total play count (logarithmic scale) |
| Recency | 20 pts | Days since last watched |
| User Breadth | 10 pts | Number of unique users who watched |
| Continuing Bonus | 5 pts | Active shows get a boost if watched |

**Tiers**: 0-20 = Strong Delete, 21-40 = Delete, 41-60 = Consider, 61-80 = Keep, 81-100 = Strong Keep

## Quick Start

```yaml
# docker-compose.yml
services:
  prunarr:
    build: .
    container_name: prunarr
    ports:
      - "8585:8585"
    environment:
      RADARR_URL: "http://radarr:7878"
      RADARR_API_KEY: "your-radarr-api-key"
      SONARR_URL: "http://sonarr:8989"
      SONARR_API_KEY: "your-sonarr-api-key"
      TAUTULLI_URL: "http://tautulli:8181"
      TAUTULLI_API_KEY: "your-tautulli-api-key"
    volumes:
      - ./config:/config
    restart: unless-stopped
```

```bash
docker compose up -d
```

Then open `http://localhost:8585` and click **Scan** to analyze your library.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RADARR_URL` | Yes | `http://radarr:7878` | Radarr base URL |
| `RADARR_API_KEY` | Yes | | Radarr API key |
| `SONARR_URL` | Yes | `http://sonarr:8989` | Sonarr base URL |
| `SONARR_API_KEY` | Yes | | Sonarr API key |
| `TAUTULLI_URL` | Yes | `http://tautulli:8181` | Tautulli base URL |
| `TAUTULLI_API_KEY` | Yes | | Tautulli API key |
| `DB_PATH` | No | `/config/prunarr.db` | SQLite database path |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `POST` | `/api/scan` | Trigger fresh scan of all services |
| `GET` | `/api/movies` | List all movies with recommendations |
| `GET` | `/api/shows` | List all TV shows with recommendations |
| `GET` | `/api/stats` | Library statistics and tier counts |
| `DELETE` | `/api/movies/{id}` | Delete movie via Radarr (with files) |
| `DELETE` | `/api/shows/{id}` | Delete show via Sonarr (with files) |

## Tech Stack

- **Backend**: Python 3.12, FastAPI, aiosqlite, httpx
- **Frontend**: Vanilla JS (ES2024+), CSS nesting, native `<dialog>`, container queries
- **Database**: SQLite (cached scan results)
- **Container**: Multi-stage Docker build, non-root user

## License

MIT
