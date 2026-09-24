from typing import Any, ClassVar

import pytest

from models.jewel import JewelOffer, JewelReward
from services import notifier_service
from services.notifier_service import NotifierService
from services.redemption_service import RedemptionPlan, RedemptionResult

REWARD = JewelReward(
    groceryRewardId="71969118",
    offerPgm="GR",
    offerProtoType="WOD_OR_POD",
    pointsRequired=900,
    discountAmount=11.0,
    offerPrice="$11 OFF",
    title="Your Next Purchase",
    clipDetails={"clippedCount": 0, "multiClipLimit": 4},
)
OFFER = JewelOffer(offerId="1", offerPgm="SC", status="C", name="Cheese", description="Save $1", offerPrice="$1")


class FakeApprise:
    sent: ClassVar[list[dict[str, Any]]] = []

    def add(self, url: str) -> bool:
        return True

    def notify(self, **kwargs: Any) -> bool:
        self.sent.append(kwargs)
        return True


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    FakeApprise.sent = []
    monkeypatch.setattr(notifier_service, "Apprise", FakeApprise)
    return FakeApprise.sent


def notify(redemption: RedemptionResult | None, clipped: list[JewelOffer] | None = None) -> None:
    NotifierService("json://localhost").notify_metrics(
        user_id="user",
        offers_skipped=[],
        offers_clipped=clipped or [],
        offers_failed=[],
        redemption=redemption,
    )


def test_redeemed(sent: list[dict[str, Any]]):
    notify(
        RedemptionResult(
            balance_before=2000,
            balance_after=200,
            best_reward=REWARD,
            plan=RedemptionPlan(reward=REWARD, count=2),
            redeemed_count=2,
        )
    )

    [message] = sent
    body = message["body"]
    assert "Redeemed $11 OFF (Your Next Purchase) 2x for 1800 points: $22.00 total" in body
    assert "Points balance: 200" in body
    assert "Unable to redeem" not in body


def test_not_enough_points_alone_is_not_sent(sent: list[dict[str, Any]]):
    notify(RedemptionResult(balance_before=500, balance_after=500, best_reward=REWARD))
    assert sent == []


def test_not_enough_points_included_with_clipped_offers(sent: list[dict[str, Any]]):
    notify(RedemptionResult(balance_before=500, balance_after=500, best_reward=REWARD), clipped=[OFFER])

    [message] = sent
    body = message["body"]
    assert "Unable to redeem: not enough points (the best cash reward, $11 OFF, needs 900)" in body
    assert "Points balance: 500" in body
    assert "Cheese" in body


def test_error_is_sent_without_point_total(sent: list[dict[str, Any]]):
    notify(RedemptionResult(balance_before=2000, balance_after=2000, error="RuntimeError: <boom>"))

    [message] = sent
    body = message["body"]
    assert "Unable to redeem: an error occurred: RuntimeError: &lt;boom&gt;" in body
    assert "Points balance" not in body


def test_partial_redemption_then_error(sent: list[dict[str, Any]]):
    notify(
        RedemptionResult(
            balance_before=2000,
            balance_after=1100,
            best_reward=REWARD,
            plan=RedemptionPlan(reward=REWARD, count=2),
            redeemed_count=1,
            error="RuntimeError: nope",
        )
    )

    [message] = sent
    body = message["body"]
    assert "Redeemed $11 OFF (Your Next Purchase) 1x for 900 points: $11.00 total" in body
    assert "Stopped early: an error occurred: RuntimeError: nope" in body
    assert "Points balance" not in body


def test_no_cash_rewards_is_sent(sent: list[dict[str, Any]]):
    notify(RedemptionResult(balance_before=2000, balance_after=2000, no_cash_rewards_found=True))

    [message] = sent
    assert "no cash rewards were found (the rewards API may have changed)" in message["body"]
    assert "Points balance: 2000" in message["body"]


def test_redemption_disabled_unchanged(sent: list[dict[str, Any]]):
    notify(None, clipped=[OFFER])

    [message] = sent
    assert "Points Rewards" not in message["body"]
    assert "Cheese" in message["body"]
