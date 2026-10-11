from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    database_url: str
    pagination_default_limit: int = 50
    pagination_max_limit: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
