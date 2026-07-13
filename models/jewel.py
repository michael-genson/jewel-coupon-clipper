from enum import Enum
from typing import Self
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


class JewelOfferStatus(Enum):
    CLIPPED = "C"
    UNCLIPPED = "U"


class JewelOffer(BaseModel):
    id: str = Field(..., alias="offerId")
    program: str = Field(..., alias="offerPgm")
    status: JewelOfferStatus
    is_deleted: bool = Field(False, alias="deleted")

    name: str = "MISSING-NAME"
    description: str = "MISSING-DESCRIPTION"
    price: str = Field("MISSING-PRICE", alias="offerPrice")

    @property
    def can_clip(self) -> bool:
        return not self.is_deleted and self.status is JewelOfferStatus.UNCLIPPED

    def __hash__(self) -> int:
        return hash(self.id)


class JewelUserConfig(BaseModel):
    id: str
    password: str
    device_token: str
    store_ids: list[str]

    root: str = "https://www.jewelosco.com"
    banner: str = ""

    @model_validator(mode="after")
    def validate_banner(self) -> Self:
        if not self.banner:
            # infer banner from root
            try:
                hostname = urlparse(self.root).hostname or ""
                labels = hostname.split(".")
                self.banner = labels[-2]
            except Exception as e:
                raise ValueError("Unable to infer banner from root, are you sure root is correct?") from e

        return self
