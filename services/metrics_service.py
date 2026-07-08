from models.jewel import JewelOffer
from models.metrics import ClipResult, OfferClipReport


class MetricsService:
    """Tracks the clip result of each offer, keyed by offer id. An offer can be seen more than once
    (e.g. once per store), so recording only overwrites an existing report if the new result is at
    least as significant - see ClipResult."""

    def __init__(self) -> None:
        self._reports_by_offer_id: dict[str, OfferClipReport] = {}

    def record(self, result: ClipResult, offer: JewelOffer) -> None:
        existing = self._reports_by_offer_id.get(offer.id)

        # Compare result - we only store the higher priority result
        if existing and existing.result > result:
            return

        self._reports_by_offer_id[offer.id] = OfferClipReport(result=result, offer=offer)

    @property
    def reports(self) -> list[OfferClipReport]:
        return list(self._reports_by_offer_id.values())

    def reports_for(self, result: ClipResult) -> list[OfferClipReport]:
        return [report for report in self.reports if report.result is result]

    def offers_for(self, result: ClipResult) -> list[JewelOffer]:
        return [report.offer for report in self.reports_for(result)]

    def count(self, result: ClipResult) -> int:
        return len(self.reports_for(result))
