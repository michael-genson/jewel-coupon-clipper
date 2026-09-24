from html import escape

from apprise import Apprise, NotifyFormat

from models.jewel import JewelOffer
from services.redemption_service import RedemptionResult
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

    def _format_redemption_section(self, redemption: RedemptionResult) -> str:
        lines: list[str] = []
        if redemption.redeemed_count and redemption.plan:
            reward = redemption.plan.reward
            dollars = (reward.discount_amount or 0) * redemption.redeemed_count
            lines.append(
                f"Redeemed {escape(reward.price)} ({escape(reward.title)}) {redemption.redeemed_count}x "
                f"for {reward.points_required * redemption.redeemed_count} points: ${dollars:.2f} total"
            )

        if reason := redemption.unable_to_redeem_reason:
            prefix = "Stopped early" if redemption.redeemed_count else "Unable to redeem"
            lines.append(f"{prefix}: {escape(reason)}")

        if not redemption.error and redemption.balance_after is not None:
            lines.append(f"Points balance: {redemption.balance_after}")

        return "<h3>Points Rewards</h3>" + "".join(f"<p>{line}</p>" for line in lines)

    def _build_metrics_notification_body(
        self,
        skipped: list[JewelOffer],
        clipped: list[JewelOffer],
        failed: list[JewelOffer],
        redemption: RedemptionResult | None = None,
    ) -> str:
        sections: list[str] = []
        if redemption:
            sections.append(self._format_redemption_section(redemption))

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
        redemption: RedemptionResult | None = None,
    ) -> None:
        total = len(offers_clipped) + len(offers_failed)
        if self.should_notify_skipped:
            total += len(offers_skipped)

        # Routinely not having enough points isn't worth a notification on its own, but gets included when one is sent
        if not total and not (redemption and redemption.is_notable):
            self.logger.info("No metrics to send")
            return

        title = self._build_notification_title(self.TITLE_METRICS, user_id)
        body = self._build_metrics_notification_body(
            skipped=offers_skipped if self.should_notify_skipped else [],
            clipped=offers_clipped,
            failed=offers_failed,
            redemption=redemption,
        )

        self.logger.debug(title)
        self.logger.debug(body)

        notifier = Apprise()
        if not notifier.add(self.apprise_url):
            self.logger.warning("Apprise URL is invalid, skipping notification")
            return

        if not notifier.notify(title=title, body=body, body_format=NotifyFormat.HTML):
            self.logger.warning("Apprise failed to send notification")
