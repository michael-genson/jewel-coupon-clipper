from datetime import date
from enum import Enum
from typing import ClassVar, Self
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


class JewelRewardClipDetails(BaseModel):
    clipped_count: int = Field(0, alias="clippedCount")
    multi_clip_limit: int = Field(1, alias="multiClipLimit")


class JewelReward(BaseModel):
    """A points reward from the rewards catalog. Redeeming one is a clip that spends points."""

    REWARD_PROGRAM: ClassVar[str] = "GR"
    # Whole-order dollars off ("$11 OFF Your Next Purchase"), as opposed to department-specific dollars
    # off (produce, bakery, ...), fee discounts, or free items
    CASH_PROTO_TYPE: ClassVar[str] = "WOD_OR_POD"

    id: str = Field(..., alias="groceryRewardId")
    program: str = Field(..., alias="offerPgm")
    proto_type: str = Field(..., alias="offerProtoType")
    points_required: int = Field(..., alias="pointsRequired")
    discount_amount: float | None = Field(None, alias="discountAmount")
    clip_details: JewelRewardClipDetails = Field(default_factory=JewelRewardClipDetails, alias="clipDetails")

    title: str = "MISSING-TITLE"
    description: str = "MISSING-DESCRIPTION"
    price: str = Field("MISSING-PRICE", alias="offerPrice")

    @property
    def is_cash(self) -> bool:
        return (
            self.program == self.REWARD_PROGRAM
            and self.proto_type == self.CASH_PROTO_TYPE
            and self.discount_amount is not None
            and self.discount_amount > 0
            and self.points_required > 0
        )

    @property
    def points_per_dollar(self) -> float:
        if self.discount_amount is None or self.discount_amount <= 0:
            raise ValueError(f"Reward {self.id} has no positive dollar amount: {self.discount_amount!r}")

        return self.points_required / self.discount_amount

    @property
    def redemptions_remaining(self) -> int:
        """Rewards can be redeemed multiple times, up to a limit (status flips to clipped after the first)"""

        return max(self.clip_details.multi_clip_limit - self.clip_details.clipped_count, 0)

    def __hash__(self) -> int:
        return hash(self.id)


class JewelPointsBucket(BaseModel):
    points: int = Field(..., alias="value")
    expires: date = Field(..., alias="validityEndDate")


class JewelPointsBalance(BaseModel):
    balance: int
    buckets: list[JewelPointsBucket] = Field(default_factory=list, alias="points")


class JewelUserConfig(BaseModel):
    id: str
    password: str
    device_token: str
    store_ids: list[str]

    root: str = "https://www.jewelosco.com"
    banner: str = ""
    apprise_url: str | None = None
    redeem_points_for_cash: bool = False

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
