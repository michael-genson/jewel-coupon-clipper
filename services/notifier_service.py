from html import escape

from apprise import Apprise, NotifyFormat

from models.jewel import JewelOffer
from utils import get_logger, get_settings


class NotifierService:
    TITLE_BASE = "Jewel Coupon Clipper"
    TITLE_METRICS = "Metrics"

    def __init__(self, apprise_url: str):
        settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)

        self.apprise_url = apprise_url
        self.should_notify_skipped = settings.notify_skipped

    def _build_notification_title(self, notification_type: str, user_id: str) -> str:
        return f"{self.TITLE_BASE}: {notification_type} ({user_id})"

    def _sorted_offers(self, offers: list[JewelOffer]) -> list[JewelOffer]:
        return sorted(offers, key=lambda x: x.name)

    def _format_metrics_header(self, header: str, qty: int) -> str:
        return f"<h3>{header} Coupons ({qty})</h3>"

    def _format_metrics_table(self, offers: list[JewelOffer]) -> str:
        cell_style = "border: 1px solid #ccc; padding: 4px 8px; text-align: left;"
        rows = "".join(
            f"<tr><td style='{cell_style}'>{escape(offer.name)}</td>"
            f"<td style='{cell_style}'>{escape(offer.description)}</td>"
            f"<td style='{cell_style}'>{escape(offer.price)}</td></tr>"
            for offer in self._sorted_offers(offers)
        )
        header = "".join(f"<th style='{cell_style}'>{h}</th>" for h in ("Name", "Description", "Price"))
        return f"<table style='border-collapse: collapse;'><tr>{header}</tr>{rows}</table>"

    def _build_metrics_notification_body(
        self, skipped: list[JewelOffer], clipped: list[JewelOffer], failed: list[JewelOffer]
    ) -> str:
        sections: list[str] = []
        for header, offers in [("Failed", failed), ("Clipped", clipped), ("Skipped", skipped)]:
            if not offers:
                continue

            sections.append(self._format_metrics_header(header, len(offers)) + self._format_metrics_table(offers))

        return "<br>".join(sections)

    def notify_metrics(
        self,
        user_id: str,
        offers_skipped: list[JewelOffer],
        offers_clipped: list[JewelOffer],
        offers_failed: list[JewelOffer],
    ) -> None:
        total = len(offers_clipped) + len(offers_failed)
        if self.should_notify_skipped:
            total += len(offers_skipped)

        if not total:
            self.logger.info("No metrics to send")
            return

        title = self._build_notification_title(self.TITLE_METRICS, user_id)
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

        if not notifier.notify(title=title, body=body, body_format=NotifyFormat.HTML):
            self.logger.warning("Apprise failed to send notification")
