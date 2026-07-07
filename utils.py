import logging
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from models.jewel import JewelUserConfig


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"
    users_file: str = "users.yaml"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=get_settings().log_level)
    return logging.getLogger(name)


@lru_cache
def get_users() -> list[JewelUserConfig]:
    path = Path(get_settings().users_file)
    data = yaml.safe_load(path.read_text())
    return [JewelUserConfig(**user) for user in data["users"]]
