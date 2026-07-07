from enum import Enum

from pydantic import BaseModel, Field


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
