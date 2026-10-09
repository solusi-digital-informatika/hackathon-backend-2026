from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://aioffice:aioffice@127.0.0.1:5435/aioffice"
    test_database_url: str = "postgresql+psycopg://aioffice:aioffice@127.0.0.1:5435/aioffice_test"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
