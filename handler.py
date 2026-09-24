from models.jewel import JewelUserConfig
from models.metrics import ClipResult
from services.jewel_service import JewelService
from services.metrics_service import MetricsService
from services.notifier_service import NotifierService
from services.redemption_service import RedemptionResult, redeem_cash_rewards
from utils import get_logger, get_settings, get_users


def process_user(user: JewelUserConfig) -> None:
    settings = get_settings()

    logger = get_logger(__name__)
    metrics = MetricsService()

    logger.info(f"Initiating JewelService on {user.banner}({user.root}) for {user.id=}...")
    with JewelService(user.id, user.password, user.root, user.banner, user.device_token) as jewel:
        for store_id in user.store_ids:
            logger.info(f"Processing offers for {user.id=}, {store_id=}")

            logger.info("Fetching offers...")
            offers = jewel.get_all_offers(store_id)

            logger.info(f"Found {len(offers)} offer{'' if len(offers) == 1 else 's'}. Clipping all...")
            for offer in offers:
                if not offer.can_clip:
                    metrics.record(ClipResult.SKIPPED, offer)
                    continue

                try:
                    jewel.clip_offer(store_id, offer)
                    metrics.record(ClipResult.CLIPPED, offer)
                except Exception:
                    logger.exception(f"Failed to clip {offer=}")
                    metrics.record(ClipResult.FAILED, offer)

        redemption: RedemptionResult | None = None
        if settings.redeem_points_for_cash:
            # Points and rewards are per-household rather than per-store, so any store works
            logger.info(f"Redeeming points for cash for {user.id=}...")
            try:
                redemption = redeem_cash_rewards(jewel, user.store_ids[0])
            except Exception as e:
                # redeem_cash_rewards records its own errors, but never let redeeming take down clipping
                logger.exception(f"Failed to redeem points for {user.id=}")
                redemption = RedemptionResult(error=f"{type(e).__name__}: {e}")

    offers_skipped = metrics.offers_for(ClipResult.SKIPPED)
    offers_clipped = metrics.offers_for(ClipResult.CLIPPED)
    offers_failed = metrics.offers_for(ClipResult.FAILED)

    logger.info(
        f"Complete for {user.id=}! Total offers: {len(metrics.reports)}. "
        f"{len(offers_clipped)=}, {len(offers_skipped)=}, {len(offers_failed)=}"
    )
    logger.debug(f"{offers_skipped=}")
    logger.debug(f"{offers_clipped=}")
    logger.debug(f"{offers_failed=}")
    if redemption:
        logger.info(
            f"Redeemed {redemption.redeemed_count} reward{'' if redemption.redeemed_count == 1 else 's'} for "
            f"{user.id=}. Points: {redemption.balance_before} -> {redemption.balance_after}"
        )
        if redemption.unable_to_redeem_reason:
            logger.info(f"Unable to redeem: {redemption.unable_to_redeem_reason}")

    apprise_url = user.apprise_url or settings.apprise_url
    if apprise_url:
        logger.info("Sending metrics notification via Apprise...")

        try:
            notifier_service = NotifierService(apprise_url)
            notifier_service.notify_metrics(
                user_id=user.id,
                offers_skipped=offers_skipped,
                offers_clipped=offers_clipped,
                offers_failed=offers_failed,
                redemption=redemption,
            )
        except Exception:
            logger.exception("Failed to notify via Apprise")


def main() -> None:
    logger = get_logger(__name__)
    users = get_users()

    for user in users:
        try:
            process_user(user)
        except Exception:
            logger.exception(f"Failed to process {user.id=}")


if __name__ == "__main__":
    main()
