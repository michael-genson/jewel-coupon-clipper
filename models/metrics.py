from enum import IntEnum

from pydantic import BaseModel

from models.jewel import JewelOffer


class ClipResult(IntEnum):
    """
    Values are ordered low to high by significance (clipped > skipped > failed). An offer can be
    seen more than once across stores (e.g. clipped in one store, then seen already-clipped and
    skipped in another) - the higher-value result should win rather than whichever was recorded last.
    """

    FAILED = 0
    SKIPPED = 1
    CLIPPED = 2


class OfferClipReport(BaseModel):
    result: ClipResult
    offer: JewelOffer
