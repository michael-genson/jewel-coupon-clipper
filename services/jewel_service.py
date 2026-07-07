import hashlib
import json
import logging
import random
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Self

from playwright.sync_api import APIResponse, Browser, BrowserContext, Page, Playwright, sync_playwright

from models.jewel import JewelOffer, JewelOfferStatus
from utils import get_logger


class JewelService:
    """
    Logs in to jewelosco.com and exposes authenticated API calls.

    If no device token is passed, one is generated automatically, however you will
    most likely run into an MFA check which is not supported.
    """

    # These are hardcoded values from Jewel
    ROOT = "https://www.jewelosco.com"
    OCP_APIM_SUB_KEY = "9e38e3f1d32a4279a49a264e0831ea46"
    SWY_API_KEY = "emjou"
    OKTA_AUTH_SERVER = "https://ciam.albertsons.com/oauth2/ausp6soxrIyPrm8rS2p6"
    OKTA_CLIENT_ID = "0oap6ku01XJqIRdl42p6"

    def __init__(self, user_id: str, password: str, device_token: str | None = None) -> None:
        self.user_id = user_id
        self.password = password
        self.device_token = device_token or uuid.uuid4().hex

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None
        self._shop_token: str | None = None
        self._logger: logging.Logger | None = None

    def __enter__(self) -> Self:
        self._playwright = sync_playwright().start()
        self._browser, self._ctx, self._page = self._set_up_browser(self._playwright)
        self._log_in()
        return self

    def __exit__(self, *args, **kwargs) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _assert_ctx_manager[T](self, val: T | None) -> T:
        if val is None:
            raise RuntimeError(f"{self.__class__.__name__} must be used as a context manager")

        return val

    @property
    def ctx(self) -> BrowserContext:
        return self._assert_ctx_manager(self._ctx)

    @property
    def page(self) -> Page:
        return self._assert_ctx_manager(self._page)

    @property
    def shop_token(self) -> str:
        return self._assert_ctx_manager(self._shop_token)

    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = get_logger(self.__class__.__name__)
        return self._logger

    def _parse_json(self, resp: APIResponse) -> dict:
        try:
            return resp.json()
        except Exception:
            self.logger.error(f"Non-JSON response ({resp.status}) from {resp.url}: {resp.text()[:2000]!r}")
            raise

    @classmethod
    def _set_up_browser(cls, p: Playwright) -> tuple[Browser, BrowserContext, Page]:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
        )
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.new_page()
        page.goto(cls.ROOT)
        page.wait_for_load_state("networkidle")

        return browser, ctx, page

    def _log_in(self) -> None:
        get_csms_headers = lambda: {  # noqa: E731
            "Accept": "application/vnd.safeway.v2+json",
            "Content-Type": "application/vnd.safeway.v2+json",
            "ocp-apim-subscription-key": self.OCP_APIM_SUB_KEY,
            "x-swy-correlation-id": str(uuid.uuid4()),
            "x-swy-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "x-swy-banner": "jewelosco",
            "x-swy-client-id": "web-portal",
            "x-aci-user-hash": hashlib.sha256(self.user_id.encode()).hexdigest(),
        }

        body = {"userId": self.user_id, "context": {"deviceToken": self.device_token}}

        resp = self.ctx.request.post(
            f"{self.ROOT}/abs/pub/cnc/csmsservice/api/csms/authn",
            params={"mode": "nonotp"},
            headers=get_csms_headers(),
            data=json.dumps(body),
        )
        r: dict = self._parse_json(resp)

        okta_id = r["oktaId"]
        state_token = r["stateToken"]
        body = {
            "id": okta_id,
            "passCode": self.password,
            "stateToken": state_token,
        }

        resp = self.ctx.request.post(
            f"{self.ROOT}/abs/pub/cnc/csmsservice/api/csms/authn/factors/password/verify",
            headers=get_csms_headers(),
            data=json.dumps(body),
        )
        r = self._parse_json(resp)

        try:
            session_token: str = r["sessionToken"]
        except KeyError:
            # See if we hit an MFA check
            is_mfa = r.get("status") == "MFA_REQUIRED"
            if is_mfa:
                self.logger.error(
                    f"MFA check required with device token '{self.device_token}'. MFA checks are not supported."
                )
            else:
                self.logger.error("An unknown exception occurred and no session token was found. Response:")
                self.logger.error(r)

            raise

        if not session_token or not isinstance(session_token, str):
            raise ValueError("Invalid session token")

        # Okta redirects to this backend servlet with an auth code; the servlet exchanges
        # it server-side and responds with a Set-Cookie for SWY_SHARED_SESSION.
        authorize_url = f"{self.OKTA_AUTH_SERVER}/v1/authorize?" + urllib.parse.urlencode(
            {
                "client_id": self.OKTA_CLIENT_ID,
                "response_type": "code",
                "response_mode": "query",
                "scope": "openid profile email offline_access used_credentials",
                "redirect_uri": f"{self.ROOT}/bin/safeway/unified/sso/authorize",
                "nonce": uuid.uuid4().hex,
                "state": uuid.uuid4().hex,
                "sessionToken": session_token,
            }
        )
        self.page.goto(authorize_url)
        # SWY_SHARED_SESSION is httpOnly, so it's invisible to document.cookie / wait_for_function;
        # poll the context's cookie jar instead.
        for _ in range(30):
            if any(c["name"] == "SWY_SHARED_SESSION" for c in self.ctx.cookies()):
                break
            self.page.wait_for_timeout(500)
        else:
            raise TimeoutError("Timed out waiting for SWY_SHARED_SESSION cookie to be set")

        resp = self.ctx.request.get(
            f"{self.ROOT}/bin/safeway/unified/userinfo",
            params={
                "rand": str(random.randint(100000, 999999)),
                "banner": "jewelosco",
            },
            headers={
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.ROOT}/",
            },
        )
        r = self._parse_json(resp)
        self.logger.debug(r)

        if r.get("userType") != "C":
            self.logger.error(f"Login did not result in an authenticated customer session. Response: {r}")
            raise RuntimeError(f"Expected userType 'C' after login, got {r.get('userType')!r}")

        self._shop_token = r["SWY_SHOP_TOKEN"]

    def get_all_offers(self, store_id: str) -> list[JewelOffer]:
        resp = self.ctx.request.get(
            f"{self.ROOT}/abs/pub/xapi/offers/companiongalleryoffer",
            params={
                "storeId": store_id,
                "rand": str(random.randint(100000, 999999)),
                "includeRedmBonusPathFPOffers": True,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/vnd.safeway.v2+json",
                "X-SWY-APPLICATION-TYPE": "web",
                "X-SWY_API_KEY": self.SWY_API_KEY,
                "X-SWY_VERSION": "1.1",
                "X-SWY_BANNER": "jewelosco",
                "Authorization": f"Bearer {self.shop_token}",
            },
        )

        r: dict = self._parse_json(resp)
        self.logger.debug(r)

        try:
            offers_data: dict[str, dict] = r["companionGalleryOffer"]
        except KeyError as e:
            self.logger.error(f"Invalid response from companiongalleryoffer: {r}")
            raise ValueError("Invalid response when fetching offers") from e

        offers: list[JewelOffer] = []
        for offer_data in offers_data.values():
            try:
                offers.append(JewelOffer(**offer_data))
            except Exception:
                try:
                    offer_name = offer_data["name"]
                except Exception:
                    offer_name = None

                self.logger.exception(f"Failed to load {offer_name=}")

        return offers

    def clip_offer(self, store_id: str, offer: JewelOffer) -> None:
        if not offer.can_clip:
            return

        resp = self.ctx.request.post(
            f"{self.ROOT}/abs/pub/web/j4u/api/offers/clip",
            params={"storeId": store_id},
            headers={
                "Content-Type": "application/json",
                "SWY_SSO_TOKEN": self.shop_token,
                "X-IBM-Client-Id": "306b9569-2a31-4fb9-93aa-08332ba3c55d",
                "X-IBM-Client-Secret": "N4tK3pW7pP6nB4kL6vN4kW0rS5lE4qH2fY0aB2rK1eP5gK4yV5",
                "X-SWY_API_KEY": self.SWY_API_KEY,
                "X-SWY_BANNER": "safeway",
                "X-SWY_VERSION": "1.0",
                "X-swyConsumerDirectoryPro": self.shop_token,
                "x-swy-correlation-id": str(uuid.uuid4()),
            },
            data=json.dumps(
                {
                    "items": [
                        {"clipType": "C", "itemId": offer.id, "itemType": offer.program},
                        {"clipType": "L", "itemId": offer.id, "itemType": offer.program},
                    ]
                }
            ),
        )
        r: dict = self._parse_json(resp)
        self.logger.debug(r)

        try:
            item_status = r["items"][0]["status"]
        except (KeyError, IndexError) as e:
            self.logger.error(f"Invalid response from clip: {r}")
            raise ValueError("Invalid response when clipping offer") from e

        if item_status != 1:
            self.logger.error(f"Failed to clip offer {offer.id}: {r}")
            raise RuntimeError(f"Failed to clip offer {offer.id}")

        offer.status = JewelOfferStatus.CLIPPED
        offer.is_deleted = False
