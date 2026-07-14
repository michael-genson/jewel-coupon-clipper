from models.jewel import JewelUserConfig
from models.metrics import ClipResult
from services.jewel_service import JewelService
from services.metrics_service import MetricsService
from services.notifier_service import NotifierService
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

    if settings.apprise_url:
        logger.info("Sending metrics notification via Apprise...")

        try:
            notifier_service = NotifierService()
            notifier_service.notify_metrics(
                offers_skipped=offers_skipped, offers_clipped=offers_clipped, offers_failed=offers_failed
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
