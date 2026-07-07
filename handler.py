from models.jewel import JewelOffer
from services.jewel_service import JewelService
from utils import get_logger, get_settings


def main() -> None:
    settings = get_settings()
    logger = get_logger(__name__)

    offers_skipped: set[JewelOffer] = set()
    offers_clipped: set[JewelOffer] = set()
    offers_failed: set[JewelOffer] = set()

    logger.info(f"Initiating JewelService for {settings.user_id=}, {settings.device_token=}...")
    with JewelService(settings.user_id, settings.password, settings.device_token) as jewel:
        for store_id in settings.store_ids:
            logger.info(f"Fetching all offers for {store_id=}...")
            offers = jewel.get_all_offers(store_id)

            logger.info(f"Clipping all offers for {store_id=}...")
            for offer in offers:
                if not offer.can_clip:
                    offers_skipped.add(offer)
                    continue

                try:
                    jewel.clip_offer(store_id, offer)
                    offers_clipped.add(offer)
                except Exception:
                    logger.exception(f"Failed to clip {offer=}")
                    offers_failed.add(offer)

    logger.info(f"Complete! {len(offers_skipped)=}, {len(offers_clipped)=}, {len(offers_failed)=}")
    logger.debug(f"{offers_skipped=}")
    logger.debug(f"{offers_clipped=}")
    logger.debug(f"{offers_failed=}")


if __name__ == "__main__":
    main()
