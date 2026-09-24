from pydantic import BaseModel

from models.jewel import JewelReward


class RedemptionPlan(BaseModel):
    reward: JewelReward
    count: int

    @property
    def total_points(self) -> int:
        return self.reward.points_required * self.count

    @property
    def total_dollars(self) -> float:
        return (self.reward.discount_amount or 0) * self.count


def best_cash_reward(rewards: list[JewelReward]) -> JewelReward | None:
    """
    The cash reward with the fewest points per dollar. Ties go to the larger dollar amount.

    Rewards that have hit their redemption limit are still considered, so a maxed-out best reward
    means nothing gets redeemed rather than falling back to a worse ratio.
    """

    candidates = [r for r in rewards if r.is_cash]
    if not candidates:
        return None

    return min(candidates, key=lambda r: (r.points_per_dollar, -(r.discount_amount or 0)))


def plan_cash_redemption(rewards: list[JewelReward], points_balance: int) -> RedemptionPlan | None:
    """
    Plans to redeem the best cash reward as many times as the balance (and the reward's redemption
    limit) allows. If the best reward is unaffordable, nothing is redeemed - we never fall back to a
    worse points-to-dollar ratio.
    """

    reward = best_cash_reward(rewards)
    if reward is None:
        return None

    count = min(points_balance // reward.points_required, reward.redemptions_remaining)
    if count <= 0:
        return None

    return RedemptionPlan(reward=reward, count=count)
