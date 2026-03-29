from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    RADARR_URL: str = "http://radarr:7878"
    RADARR_API_KEY: str = ""
    SONARR_URL: str = "http://sonarr:8989"
    SONARR_API_KEY: str = ""
    TAUTULLI_URL: str = "http://tautulli:8181"
    TAUTULLI_API_KEY: str = ""
    DB_PATH: str = "/config/prunarr.db"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
