from typing import cast

import pytest

from models.jewel import JewelPointsBalance, JewelReward
from services import redemption_service
from services.jewel_service import JewelService, RewardBalanceUpdatingError
from services.redemption_service import redeem_cash_rewards


def make_reward(id: str, points: int, dollars: float | None, proto_type: str = "WOD_OR_POD") -> JewelReward:
    return JewelReward(
        groceryRewardId=id,
        offerPgm="GR",
        offerProtoType=proto_type,
        pointsRequired=points,
        discountAmount=dollars,
        offerPrice=f"${dollars:g} OFF" if dollars else "FREE",
        clipDetails={"clippedCount": 0, "multiClipLimit": 4},
    )


class FakeJewel:
    """Tracks a points balance and deducts from it on each successful redemption."""

    def __init__(self, balance: int, rewards: list[JewelReward], redeem_errors: list[Exception] | None = None) -> None:
        self.balance = balance
        self.rewards = rewards
        self.redeem_errors = list(redeem_errors or [])  # raised in order, one per redeem call
        self.redeem_calls: list[str] = []

    def get_points_balance(self) -> JewelPointsBalance:
        return JewelPointsBalance(balance=self.balance)

    def get_all_rewards(self, store_id: str) -> list[JewelReward]:
        return self.rewards

    def redeem_reward(self, store_id: str, reward: JewelReward) -> None:
        self.redeem_calls.append(reward.id)
        if self.redeem_errors:
            raise self.redeem_errors.pop(0)

        self.balance -= reward.points_required
        reward.clip_details.clipped_count += 1


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(redemption_service.time, "sleep", sleeps.append)
    return sleeps


def run(jewel: FakeJewel) -> redemption_service.RedemptionResult:
    return redeem_cash_rewards(cast(JewelService, jewel), "3422")


def test_redeems_best_reward_as_many_times_as_affordable():
    jewel = FakeJewel(2000, [make_reward("best", 900, 11.0), make_reward("worse", 700, 8.0)])
    result = run(jewel)

    assert jewel.redeem_calls == ["best", "best"]
    assert result.redeemed_count == 2
    assert result.balance_before == 2000
    assert result.balance_after == 200
    assert result.error is None
    assert result.unable_to_redeem_reason is None


def test_nothing_affordable_redeems_nothing():
    jewel = FakeJewel(800, [make_reward("best", 900, 11.0), make_reward("worse", 700, 8.0)])
    result = run(jewel)

    assert jewel.redeem_calls == []
    assert result.plan is None
    assert result.redeemed_count == 0
    assert result.balance_after == 800
    assert not result.is_notable
    assert result.unable_to_redeem_reason == "not enough points (the best cash reward, $11 OFF, needs 900)"


def test_maxed_out_best_reward_reason():
    best = make_reward("best", 900, 11.0)
    best.clip_details.clipped_count = 4
    jewel = FakeJewel(2000, [best, make_reward("worse", 700, 8.0)])
    result = run(jewel)

    assert jewel.redeem_calls == []
    reason = result.unable_to_redeem_reason
    assert reason is not None
    assert "already been redeemed the maximum 4 times" in reason


def test_no_cash_rewards_is_flagged():
    jewel = FakeJewel(1000, [make_reward("produce", 400, 6.0, proto_type="DEPARTMENT")])
    result = run(jewel)

    assert jewel.redeem_calls == []
    assert result.no_cash_rewards_found
    assert result.is_notable


def test_retries_while_balance_is_updating(no_sleep: list[float]):
    jewel = FakeJewel(1000, [make_reward("best", 900, 11.0)], redeem_errors=[RewardBalanceUpdatingError()])
    result = run(jewel)

    assert jewel.redeem_calls == ["best", "best"]
    assert result.redeemed_count == 1
    assert redemption_service.BALANCE_UPDATING_RETRY_DELAY_SECONDS in no_sleep


def test_gives_up_after_max_balance_updating_attempts():
    errors: list[Exception] = [RewardBalanceUpdatingError() for _ in range(10)]
    jewel = FakeJewel(1000, [make_reward("best", 900, 11.0)], redeem_errors=errors)
    result = run(jewel)

    assert len(jewel.redeem_calls) == redemption_service.BALANCE_UPDATING_MAX_ATTEMPTS
    assert result.redeemed_count == 0
    assert result.error is not None


def test_other_errors_stop_without_retrying():
    jewel = FakeJewel(2000, [make_reward("best", 900, 11.0)], redeem_errors=[RuntimeError("nope")])
    result = run(jewel)

    assert jewel.redeem_calls == ["best"]
    assert result.redeemed_count == 0
    assert result.error == "RuntimeError: nope"
    assert result.unable_to_redeem_reason == "an error occurred: RuntimeError: nope"


def test_fetch_failure_is_recorded_not_raised():
    jewel = FakeJewel(2000, [make_reward("best", 900, 11.0)])

    def fail() -> JewelPointsBalance:
        raise ValueError("bad response")

    jewel.get_points_balance = fail  # type: ignore[method-assign]
    result = run(jewel)

    assert jewel.redeem_calls == []
    assert result.error == "ValueError: bad response"
    assert result.balance_before is None
    assert result.is_notable


def test_long_errors_are_truncated():
    jewel = FakeJewel(2000, [make_reward("best", 900, 11.0)], redeem_errors=[RuntimeError("x" * 1000)])
    result = run(jewel)

    assert result.error is not None
    assert len(result.error) == 300
    assert result.error.endswith("...")


def test_stops_when_balance_drops_unexpectedly():
    jewel = FakeJewel(2000, [make_reward("best", 900, 11.0)])
    original_redeem = jewel.redeem_reward

    def redeem_and_lose_points(store_id: str, reward: JewelReward) -> None:
        original_redeem(store_id, reward)
        jewel.balance -= 500  # e.g. points spent elsewhere mid-run

    jewel.redeem_reward = redeem_and_lose_points  # type: ignore[method-assign]
    result = run(jewel)

    assert jewel.redeem_calls == ["best"]
    assert result.redeemed_count == 1
    assert result.balance_after == 600
    assert result.unable_to_redeem_reason == "the points balance dropped unexpectedly after 1 of 2"
