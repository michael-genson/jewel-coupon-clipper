import json
from pathlib import Path

import pytest

from models.jewel import JewelPointsBalance, JewelReward
from services.redemption_service import best_cash_reward, plan_cash_redemption

FIXTURES = Path(__file__).parent / "fixtures" / "rewards"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def catalog() -> list[JewelReward]:
    return [JewelReward(**r) for r in load_fixture("catalog_before.json")["grOffers"]]


def make_reward(
    id: str,
    points: int,
    dollars: float | None,
    proto_type: str = "WOD_OR_POD",
    program: str = "GR",
    clipped: int = 0,
    limit: int = 4,
) -> JewelReward:
    return JewelReward(
        groceryRewardId=id,
        offerPgm=program,
        offerProtoType=proto_type,
        pointsRequired=points,
        discountAmount=dollars,
        clipDetails={"clippedCount": clipped, "multiClipLimit": limit},
    )


def test_catalog_fixture_cash_rewards(catalog: list[JewelReward]):
    cash = {(r.points_required, r.discount_amount) for r in catalog if r.is_cash}
    assert cash == {(900, 11.0), (700, 8.0)}


def test_catalog_fixture_best_reward(catalog: list[JewelReward]):
    best = best_cash_reward(catalog)
    assert best is not None
    assert (best.points_required, best.discount_amount) == (900, 11.0)


def test_scorecard_fixture_parses():
    scorecard = load_fixture("scorecard_before.json")["scorecards"][0]
    balance = JewelPointsBalance(**scorecard)
    assert balance.balance == 1112
    assert [b.points for b in balance.buckets] == [574, 538]


@pytest.mark.parametrize(
    ("balance", "expected_count"),
    [(1112, 1), (1800, 2), (899, None), (0, None)],
)
def test_catalog_fixture_plan(catalog: list[JewelReward], balance: int, expected_count: int | None):
    plan = plan_cash_redemption(catalog, balance)
    if expected_count is None:
        assert plan is None
    else:
        assert plan is not None
        assert plan.reward.points_required == 900
        assert plan.count == expected_count


def test_redeems_as_many_times_as_affordable():
    plan = plan_cash_redemption([make_reward("a", 200, 3.0)], 500)
    assert plan is not None
    assert plan.count == 2
    assert plan.total_points == 400
    assert plan.total_dollars == 6.0


def test_does_not_fall_back_to_worse_ratio_when_best_is_unaffordable():
    rewards = [make_reward("best", 500, 10.0), make_reward("worse", 100, 1.0)]
    assert plan_cash_redemption(rewards, 100) is None


def test_count_capped_by_redemptions_remaining():
    plan = plan_cash_redemption([make_reward("a", 100, 2.0, clipped=3, limit=4)], 1000)
    assert plan is not None
    assert plan.count == 1


def test_does_not_fall_back_to_worse_ratio_when_best_is_maxed_out():
    rewards = [make_reward("best", 100, 5.0, clipped=4, limit=4), make_reward("worse", 100, 4.0)]
    assert plan_cash_redemption(rewards, 1000) is None


def test_tie_goes_to_larger_dollar_amount():
    rewards = [make_reward("small", 100, 1.0), make_reward("large", 500, 5.0)]
    best = best_cash_reward(rewards)
    assert best is not None
    assert best.id == "large"


@pytest.mark.parametrize(
    "reward",
    [
        make_reward("department", 100, 50.0, proto_type="DEPARTMENT"),
        make_reward("free-item", 100, None, proto_type="ITEM_DISCOUNT"),
        make_reward("not-a-reward", 100, 50.0, program="SC"),
        make_reward("zero-dollars", 100, 0.0),
        make_reward("negative-dollars", 100, -5.0),
        make_reward("zero-points", 0, 5.0),
    ],
    ids=lambda r: r.id,
)
def test_non_cash_rewards_are_ignored(reward: JewelReward):
    assert not reward.is_cash
    assert plan_cash_redemption([reward], 10_000) is None
