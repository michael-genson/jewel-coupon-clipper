import time

from pydantic import BaseModel

from models.jewel import JewelReward
from services.jewel_service import JewelService, RewardBalanceUpdatingError
from utils import get_logger

# The site rejects a redemption while the balance is still updating from a previous one
# ("please check back in a few minutes"); the redemption didn't happen, so it's safe to retry
BALANCE_UPDATING_MAX_ATTEMPTS = 3
BALANCE_UPDATING_RETRY_DELAY_SECONDS = 30

# Give the balance a moment to reflect a redemption before checking it for the next one
POST_REDEEM_DELAY_SECONDS = 3


class RedemptionPlan(BaseModel):
    reward: JewelReward
    count: int

    @property
    def total_points(self) -> int:
        return self.reward.points_required * self.count

    @property
    def total_dollars(self) -> float:
        return (self.reward.discount_amount or 0) * self.count


class RedemptionResult(BaseModel):
    balance_before: int | None = None
    balance_after: int | None = None
    best_reward: JewelReward | None = None
    plan: RedemptionPlan | None = None
    redeemed_count: int = 0
    error: str | None = None
    no_cash_rewards_found: bool = False

    @property
    def is_notable(self) -> bool:
        """Whether this is worth a notification on its own (as opposed to routinely not having enough points)"""

        return bool(self.redeemed_count or self.error or self.no_cash_rewards_found)

    @property
    def unable_to_redeem_reason(self) -> str | None:
        """Why nothing (or less than planned) was redeemed, if anything went short"""

        if self.error:
            return f"an error occurred: {self.error}"
        if self.no_cash_rewards_found:
            return "no cash rewards were found (the rewards API may have changed)"
        if self.plan and self.redeemed_count < self.plan.count:
            return f"the points balance dropped unexpectedly after {self.redeemed_count} of {self.plan.count}"
        if self.redeemed_count:
            return None

        reward = self.best_reward
        if reward is None:
            return "no cash rewards were found"
        if reward.redemptions_remaining == 0:
            return (
                f"the best cash reward ({reward.price}, {reward.points_required} points) has already been "
                f"redeemed the maximum {reward.clip_details.multi_clip_limit} times"
            )
        return f"not enough points (the best cash reward, {reward.price}, needs {reward.points_required})"


def _describe_error(e: Exception, max_length: int = 300) -> str:
    description = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
    return description if len(description) <= max_length else description[: max_length - 3] + "..."


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


def _redeem_with_retry(jewel: JewelService, store_id: str, reward: JewelReward) -> None:
    logger = get_logger(__name__)
    for attempt in range(1, BALANCE_UPDATING_MAX_ATTEMPTS + 1):
        try:
            jewel.redeem_reward(store_id, reward)
            return
        except RewardBalanceUpdatingError:
            if attempt == BALANCE_UPDATING_MAX_ATTEMPTS:
                raise

            logger.warning(
                f"Points balance is still updating (attempt {attempt}/{BALANCE_UPDATING_MAX_ATTEMPTS}), "
                f"retrying in {BALANCE_UPDATING_RETRY_DELAY_SECONDS}s..."
            )
            time.sleep(BALANCE_UPDATING_RETRY_DELAY_SECONDS)


def redeem_cash_rewards(jewel: JewelService, store_id: str) -> RedemptionResult:
    """
    Redeems the best cash reward as many times as the points balance allows (see plan_cash_redemption).
    Redemptions are made one at a time, and the balance is re-checked before each one after the first.
    Any unexpected error stops further redemptions and is recorded on the result rather than raised.
    """

    logger = get_logger(__name__)

    try:
        balance = jewel.get_points_balance().balance
        rewards = jewel.get_all_rewards(store_id)
    except Exception as e:
        logger.exception("Failed to fetch points balance or rewards")
        return RedemptionResult(error=_describe_error(e))

    result = RedemptionResult(balance_before=balance, balance_after=balance, best_reward=best_cash_reward(rewards))

    if not any(r.is_cash for r in rewards):
        result.no_cash_rewards_found = True
        if balance > 0:
            logger.warning(
                f"Found {len(rewards)} rewards but none are cash rewards, even though there are {balance} points "
                "to spend. The rewards API may have changed."
            )
        return result

    plan = plan_cash_redemption(rewards, balance)
    result.plan = plan
    if plan is None:
        logger.info(f"Not redeeming any points: {result.unable_to_redeem_reason}")
        return result

    reward = plan.reward
    logger.info(
        f"Redeeming {reward.title!r} ({reward.points_required} points for ${reward.discount_amount}) "
        f"{plan.count} time{'' if plan.count == 1 else 's'} with {balance} points"
    )

    for i in range(plan.count):
        try:
            if i > 0:
                time.sleep(POST_REDEEM_DELAY_SECONDS)
                result.balance_after = jewel.get_points_balance().balance
                if result.balance_after < reward.points_required:
                    logger.warning(
                        f"Balance is down to {result.balance_after} points, stopping after "
                        f"{result.redeemed_count}/{plan.count} redemptions"
                    )
                    break

            _redeem_with_retry(jewel, store_id, reward)
        except Exception as e:
            logger.exception(f"Failed to redeem {reward.id}, stopping after {result.redeemed_count}/{plan.count}")
            result.error = _describe_error(e)
            break

        result.redeemed_count += 1
        logger.info(f"Redeemed {reward.id} ({result.redeemed_count}/{plan.count})")

    if result.redeemed_count:
        try:
            time.sleep(POST_REDEEM_DELAY_SECONDS)
            result.balance_after = jewel.get_points_balance().balance
        except Exception:
            logger.exception("Failed to fetch points balance after redeeming")

    return result
