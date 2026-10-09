from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://aioffice:aioffice@127.0.0.1:5435/aioffice"
    test_database_url: str = "postgresql+psycopg://aioffice:aioffice@127.0.0.1:5435/aioffice_test"
    moodboard_storage_dir: str = "./data/moodboards"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_vision_model: str = ""
    ai_timeout_seconds: float = 120
    moodboard_max_file_bytes: int = 10 * 1024 * 1024
    moodboard_max_total_bytes: int = 50 * 1024 * 1024
    moodboard_max_sources: int = 10
    moodboard_max_pixels: int = 40_000_000
    moodboard_analysis_size: int = 2048
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
