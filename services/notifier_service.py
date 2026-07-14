from apprise import Apprise

from models.jewel import JewelOffer
from utils import get_logger, get_settings


class NotifierService:
    TITLE_BASE = "Jewel Coupon Clipper"
    TITLE_METRICS = "Metrics"

    def __init__(self):
        settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)

        self.apprise_url = settings.apprise_url
        self.should_notify_skipped = settings.notify_skipped

    def _build_notification_title(self, notification_type: str) -> str:
        return f"{self.TITLE_BASE}: {notification_type}"

    def _sorted_offers(self, offers: list[JewelOffer]) -> list[JewelOffer]:
        return sorted(offers, key=lambda x: x.name)

    def _format_metrics_header(self, header: str) -> str:
        return f"\n==={header} Coupons===\n"

    def _format_metrics_offer(self, offer: JewelOffer) -> str:
        return f"{offer.name}: {offer.description} ({offer.price})"

    def _build_metrics_notification_body(
        self, skipped: list[JewelOffer], clipped: list[JewelOffer], failed: list[JewelOffer]
    ) -> str:
        sections: list[str] = []
        for header, offers in [("Failed", failed), ("Clipped", clipped), ("Skipped", skipped)]:
            if not offers:
                continue

            section: list[str] = [self._format_metrics_header(header)]
            for offer in self._sorted_offers(offers):
                section.append(self._format_metrics_offer(offer))

            sections.append("\n".join(section))

        return "\n".join(sections)

    def notify_metrics(
        self, offers_skipped: list[JewelOffer], offers_clipped: list[JewelOffer], offers_failed: list[JewelOffer]
    ) -> None:
        if not self.apprise_url:
            self.logger.info("Apprise URL is empty")
            return

        total = len(offers_clipped) + len(offers_failed)
        if self.should_notify_skipped:
            total += len(offers_skipped)

        if not total:
            self.logger.info("No metrics to send")
            return

        title = self._build_notification_title(self.TITLE_METRICS)
        body = self._build_metrics_notification_body(
            skipped=offers_skipped if self.should_notify_skipped else [],
            clipped=offers_clipped,
            failed=offers_failed,
        )

        self.logger.debug(title)
        self.logger.debug(body)

        notifier = Apprise()
        if not notifier.add(self.apprise_url):
            self.logger.warning("Apprise URL is invalid, skipping notification")
            return

        if not notifier.notify(title=title, body=body):
            self.logger.warning("Apprise failed to send notification")
