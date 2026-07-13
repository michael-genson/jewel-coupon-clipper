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

    # Shared across all Albertsons-family banner sites (jewelosco, safeway, vons, albertsons, ...) -
    # only the per-user root/banner in users.yaml differ.
    ocp_apim_sub_key: str = "9e38e3f1d32a4279a49a264e0831ea46"
    swy_api_key: str = "emjou"
    okta_auth_server: str = "https://ciam.albertsons.com/oauth2/ausp6soxrIyPrm8rS2p6"
    okta_client_id: str = "0oap6ku01XJqIRdl42p6"
    ibm_client_id: str = "306b9569-2a31-4fb9-93aa-08332ba3c55d"
    ibm_client_secret: str = "N4tK3pW7pP6nB4kL6vN4kW0rS5lE4qH2fY0aB2rK1eP5gK4yV5"


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
