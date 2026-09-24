import json
from pathlib import Path
from typing import Any

import pytest

from models.jewel import JewelOffer, JewelOfferStatus, JewelReward
from services.jewel_service import JewelService, RewardBalanceUpdatingError

FIXTURES = Path(__file__).parent / "fixtures" / "rewards"


class FakeResponse:
    def __init__(self, body: Any) -> None:
        self.body = body
        self.status = 200
        self.url = "https://example.test"

    def json(self) -> Any:
        return self.body

    def text(self) -> str:
        return json.dumps(self.body)


class FakeRequest:
    def __init__(self, body: Any) -> None:
        self.body = body
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs, "data": json.loads(kwargs["data"])})
        return FakeResponse(self.body)


class FakeContext:
    def __init__(self, body: Any) -> None:
        self.request = FakeRequest(body)


def make_service(response_body: Any) -> tuple[JewelService, FakeRequest]:
    """A JewelService that skips login and answers every POST with `response_body`."""

    service = JewelService("user", "password", "https://www.jewelosco.com", "jewelosco", "device-token")
    ctx = FakeContext(response_body)
    service._ctx = ctx  # type: ignore[assignment]
    service._shop_token = "shop-token"
    return service, ctx.request


def clip_response(status: int, **extra: Any) -> dict:
    return {"items": [{"clipType": "C", "itemId": "1", "status": status, **extra}]}


@pytest.fixture
def offer() -> JewelOffer:
    return JewelOffer(offerId="offer-1", offerPgm="SC", status="U")


@pytest.fixture
def reward() -> JewelReward:
    catalog = json.loads((FIXTURES / "catalog_before.json").read_text())["grOffers"]
    return JewelReward(**next(r for r in catalog if r["groceryRewardId"] == "82573078"))


def test_clip_offer_sends_expected_request(offer: JewelOffer):
    service, request = make_service(clip_response(1))
    service.clip_offer("3422", offer)

    [call] = request.calls
    assert call["url"] == "https://www.jewelosco.com/abs/pub/web/j4u/api/offers/clip"
    assert call["params"] == {"storeId": "3422"}
    assert call["headers"]["SWY_SSO_TOKEN"] == "shop-token"
    assert call["data"] == {
        "items": [
            {"clipType": "C", "itemId": "offer-1", "itemType": "SC"},
            {"clipType": "L", "itemId": "offer-1", "itemType": "SC"},
        ]
    }
    assert offer.status is JewelOfferStatus.CLIPPED


def test_clip_offer_skips_already_clipped(offer: JewelOffer):
    offer.status = JewelOfferStatus.CLIPPED
    service, request = make_service(clip_response(1))
    service.clip_offer("3422", offer)
    assert request.calls == []


def test_clip_offer_failure_raises(offer: JewelOffer):
    service, _ = make_service(clip_response(0))
    with pytest.raises(RuntimeError):
        service.clip_offer("3422", offer)
    assert offer.status is JewelOfferStatus.UNCLIPPED


@pytest.mark.parametrize("body", [{}, {"items": []}, {"items": [{}]}, {"items": None}])
def test_clip_malformed_response_raises(offer: JewelOffer, body: dict):
    service, _ = make_service(body)
    with pytest.raises(ValueError):
        service.clip_offer("3422", offer)


def test_redeem_reward_sends_expected_request(reward: JewelReward):
    # The real response from the live test redemption
    redeem_response = json.loads((FIXTURES / "redeem_response.json").read_text())
    expected_request = json.loads((FIXTURES / "redeem_request.json").read_text())

    service, request = make_service(redeem_response)
    service.redeem_reward("3422", reward)

    [call] = request.calls
    assert call["url"] == expected_request["url"]
    assert call["params"] == expected_request["params"]
    assert call["data"] == expected_request["body"]
    assert reward.clip_details.clipped_count == 1
    assert reward.redemptions_remaining == 3


@pytest.mark.parametrize("error_code", ["EMJOC8024E", "EMJOC8025E"])
def test_redeem_reward_balance_updating(reward: JewelReward, error_code: str):
    service, _ = make_service(clip_response(0, errorCd=error_code))
    with pytest.raises(RewardBalanceUpdatingError):
        service.redeem_reward("3422", reward)
    assert reward.clip_details.clipped_count == 0


def test_redeem_reward_other_failure(reward: JewelReward):
    service, _ = make_service(clip_response(0, errorCd="EMJOC4007E", errorMsg="already clipped"))
    with pytest.raises(RuntimeError, match="EMJOC4007E") as exc_info:
        service.redeem_reward("3422", reward)
    assert not isinstance(exc_info.value, RewardBalanceUpdatingError)
    assert reward.clip_details.clipped_count == 0
