"""Configuration and persistent settings for Prunarr.

Bootstrap config comes from environment variables via pydantic-settings.
User-configurable settings are stored in SQLite with a layered priority:
    DB values > environment variables > defaults.
"""

import sqlite3

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    RADARR_URL: str = "http://radarr:7878"
    RADARR_API_KEY: str = ""
    SONARR_URL: str = "http://sonarr:8989"
    SONARR_API_KEY: str = ""
    TAUTULLI_URL: str = "http://tautulli:8181"
    TAUTULLI_API_KEY: str = ""
    AUTH_PASSWORD: str = ""
    DB_PATH: str = "/config/prunarr.db"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# ---------------------------------------------------------------------------
# Persistent settings table
# ---------------------------------------------------------------------------

_SETTINGS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Configurable keys – metadata used by both backend logic and the settings UI
# ---------------------------------------------------------------------------

CONFIGURABLE_KEYS: dict[str, dict] = {
    # -- connections --
    "radarr_url": {
        "default": "http://radarr:7878",
        "group": "connections",
        "label": "Radarr URL",
        "type": "url",
        "placeholder": "http://radarr:7878",
    },
    "radarr_api_key": {
        "default": "",
        "group": "connections",
        "label": "Radarr API Key",
        "type": "password",
        "placeholder": "your-radarr-api-key",
    },
    "sonarr_url": {
        "default": "http://sonarr:8989",
        "group": "connections",
        "label": "Sonarr URL",
        "type": "url",
        "placeholder": "http://sonarr:8989",
    },
    "sonarr_api_key": {
        "default": "",
        "group": "connections",
        "label": "Sonarr API Key",
        "type": "password",
        "placeholder": "your-sonarr-api-key",
    },
    "tautulli_url": {
        "default": "http://tautulli:8181",
        "group": "connections",
        "label": "Tautulli URL",
        "type": "url",
        "placeholder": "http://tautulli:8181",
    },
    "tautulli_api_key": {
        "default": "",
        "group": "connections",
        "label": "Tautulli API Key",
        "type": "password",
        "placeholder": "your-tautulli-api-key",
    },
    # -- scoring weights --
    "weight_ratings": {
        "default": 30,
        "group": "scoring",
        "label": "Ratings Weight",
        "type": "number",
        "placeholder": "30",
        "min": 0,
        "max": 100,
    },
    "weight_engagement": {
        "default": 35,
        "group": "scoring",
        "label": "Engagement Weight",
        "type": "number",
        "placeholder": "35",
        "min": 0,
        "max": 100,
    },
    "weight_recency": {
        "default": 20,
        "group": "scoring",
        "label": "Recency Weight",
        "type": "number",
        "placeholder": "20",
        "min": 0,
        "max": 100,
    },
    "weight_breadth": {
        "default": 10,
        "group": "scoring",
        "label": "User Breadth Weight",
        "type": "number",
        "placeholder": "10",
        "min": 0,
        "max": 100,
    },
    "weight_continuing": {
        "default": 5,
        "group": "scoring",
        "label": "Continuing Series Weight",
        "type": "number",
        "placeholder": "5",
        "min": 0,
        "max": 100,
    },
    # -- tier thresholds --
    "tier_strong_delete": {
        "default": 20,
        "group": "tiers",
        "label": "Strong Delete Threshold",
        "type": "number",
        "placeholder": "20",
        "min": 0,
        "max": 100,
    },
    "tier_delete": {
        "default": 40,
        "group": "tiers",
        "label": "Delete Threshold",
        "type": "number",
        "placeholder": "40",
        "min": 0,
        "max": 100,
    },
    "tier_consider": {
        "default": 60,
        "group": "tiers",
        "label": "Consider Threshold",
        "type": "number",
        "placeholder": "60",
        "min": 0,
        "max": 100,
    },
    "tier_keep": {
        "default": 80,
        "group": "tiers",
        "label": "Keep Threshold",
        "type": "number",
        "placeholder": "80",
        "min": 0,
        "max": 100,
    },
    # -- general --
    "auto_scan_on_start": {
        "default": False,
        "group": "general",
        "label": "Auto Scan on Start",
        "type": "bool",
        "placeholder": "",
    },
    "delete_files_on_remove": {
        "default": True,
        "group": "general",
        "label": "Delete Files on Remove",
        "type": "bool",
        "placeholder": "",
    },
    "add_exclusion_on_remove": {
        "default": True,
        "group": "general",
        "label": "Add Exclusion on Remove",
        "type": "bool",
        "placeholder": "",
    },
    "app_name": {
        "default": "Prunarr",
        "group": "general",
        "label": "App Name",
        "type": "text",
        "placeholder": "Prunarr",
    },
    "auth_enabled": {
        "default": False,
        "group": "general",
        "label": "Enable Password Protection",
        "type": "bool",
        "placeholder": "",
    },
    "auth_password": {
        "default": "",
        "group": "general",
        "label": "Password (bcrypt hash stored)",
        "type": "password",
        "placeholder": "Enter new password",
    },
}

# Mapping from configurable key names to the corresponding env-var names on
# the bootstrap Settings object.  Only keys that have a Settings counterpart
# are listed here.
_KEY_TO_ENV_ATTR: dict[str, str] = {
    "radarr_url": "RADARR_URL",
    "radarr_api_key": "RADARR_API_KEY",
    "sonarr_url": "SONARR_URL",
    "sonarr_api_key": "SONARR_API_KEY",
    "tautulli_url": "TAUTULLI_URL",
    "tautulli_api_key": "TAUTULLI_API_KEY",
    "auth_password": "AUTH_PASSWORD",
}


def _ensure_settings_table(db_path: str) -> None:
    """Create the app_settings table if it does not already exist."""
    con = sqlite3.connect(db_path)
    try:
        con.execute(_SETTINGS_CREATE_SQL)
        con.commit()
    finally:
        con.close()


def _coerce_value(raw: str, meta: dict) -> object:
    """Convert a stored string value to the Python type implied by *meta*."""
    typ = meta.get("type", "text")
    if typ == "bool":
        return raw.lower() in ("true", "1", "yes")
    if typ == "number":
        try:
            return int(raw)
        except ValueError:
            return float(raw)
    return raw


def _serialize_value(value: object) -> str:
    """Convert a Python value to its string representation for storage."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def get_all_settings(db_path: str | None = None) -> dict[str, object]:
    """Return every configurable key with its effective value.

    Priority: DB value > environment variable (via Settings) > default.
    """
    db_path = db_path or settings.DB_PATH
    _ensure_settings_table(db_path)

    # 1. Start with defaults
    merged: dict[str, object] = {
        key: meta["default"] for key, meta in CONFIGURABLE_KEYS.items()
    }

    # 2. Override with environment-sourced values from the Settings object
    for key, attr in _KEY_TO_ENV_ATTR.items():
        env_val = getattr(settings, attr, None)
        if env_val is not None and env_val != "":
            merged[key] = env_val

    # 3. Override with DB-stored values
    con = sqlite3.connect(db_path)
    try:
        cursor = con.execute("SELECT key, value FROM app_settings")
        for row in cursor.fetchall():
            key, raw = row
            if key in CONFIGURABLE_KEYS:
                merged[key] = _coerce_value(raw, CONFIGURABLE_KEYS[key])
    finally:
        con.close()

    return merged


def get_setting(key: str, db_path: str | None = None) -> object:
    """Return the effective value for a single configurable key."""
    if key not in CONFIGURABLE_KEYS:
        raise KeyError(f"Unknown setting: {key}")

    db_path = db_path or settings.DB_PATH
    _ensure_settings_table(db_path)

    meta = CONFIGURABLE_KEYS[key]

    # Check DB first (highest priority)
    con = sqlite3.connect(db_path)
    try:
        cursor = con.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        if row is not None:
            return _coerce_value(row[0], meta)
    finally:
        con.close()

    # Then env var
    attr = _KEY_TO_ENV_ATTR.get(key)
    if attr is not None:
        env_val = getattr(settings, attr, None)
        if env_val is not None and env_val != "":
            return env_val

    # Fall back to default
    return meta["default"]


def save_settings(updates: dict[str, object], db_path: str | None = None) -> None:
    """Persist one or more settings to the database.

    *updates* maps configurable key names to their new values.
    """
    db_path = db_path or settings.DB_PATH
    _ensure_settings_table(db_path)

    con = sqlite3.connect(db_path)
    try:
        for key, value in updates.items():
            if key not in CONFIGURABLE_KEYS:
                continue
            con.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, _serialize_value(value)),
            )
        con.commit()
    finally:
        con.close()


def get_effective_service_config(db_path: str | None = None) -> dict[str, str]:
    """Return the effective connection settings for external services."""
    all_settings = get_all_settings(db_path)
    return {
        "radarr_url": str(all_settings.get("radarr_url", "")),
        "radarr_api_key": str(all_settings.get("radarr_api_key", "")),
        "sonarr_url": str(all_settings.get("sonarr_url", "")),
        "sonarr_api_key": str(all_settings.get("sonarr_api_key", "")),
        "tautulli_url": str(all_settings.get("tautulli_url", "")),
        "tautulli_api_key": str(all_settings.get("tautulli_api_key", "")),
    }


def get_scoring_weights(db_path: str | None = None) -> dict[str, float]:
    """Return the effective scoring weights as floats."""
    all_settings = get_all_settings(db_path)
    return {
        "ratings": float(all_settings.get("weight_ratings", 30)),
        "engagement": float(all_settings.get("weight_engagement", 35)),
        "recency": float(all_settings.get("weight_recency", 20)),
        "breadth": float(all_settings.get("weight_breadth", 10)),
        "continuing": float(all_settings.get("weight_continuing", 5)),
    }


def get_tier_thresholds(db_path: str | None = None) -> dict[str, float]:
    """Return the effective tier thresholds as floats."""
    all_settings = get_all_settings(db_path)
    return {
        "strong_delete": float(all_settings.get("tier_strong_delete", 20)),
        "delete": float(all_settings.get("tier_delete", 40)),
        "consider": float(all_settings.get("tier_consider", 60)),
        "keep": float(all_settings.get("tier_keep", 80)),
    }
