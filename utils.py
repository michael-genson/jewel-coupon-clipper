import logging
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    user_id: str
    password: str
    device_token: str
    store_ids: Annotated[list[str], NoDecode]

    log_level: str = "INFO"

    @field_validator("store_ids", mode="before")
    @classmethod
    def _split_store_ids(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=get_settings().log_level)
    return logging.getLogger(name)
