import hashlib
import json
import logging
import random
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Self

from playwright.sync_api import APIResponse, Browser, BrowserContext, Page, Playwright, sync_playwright

from models.jewel import JewelOffer, JewelOfferStatus
from utils import get_logger, get_settings


class MFARequiredError(RuntimeError):
    """Raised when the login flow requires MFA, which this tool doesn't support."""


class JewelService:
    """
    Logs in to an Albertsons-family banner site (jewelosco.com, safeway.com, vons.com,
    albertsons.com, ...) and exposes authenticated API calls.

    If no device token is passed, one is generated automatically, however you will
    most likely run into an MFA check which is not supported.
    """

    # Login intermittently gets blocked by anti-bot protection even under otherwise-identical
    # conditions - retrying a few times clears it up more often than not.
    LOGIN_MAX_ATTEMPTS = 3
    LOGIN_RETRY_DELAY_SECONDS = 5

    def __init__(
        self,
        user_id: str,
        password: str,
        root: str,
        banner: str,
        device_token: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.password = password
        self.root = root.rstrip("/")
        self.banner = banner
        self.device_token = device_token or uuid.uuid4().hex

        # These are constant across all Albertsons-family banners
        settings = get_settings()
        self.ocp_apim_sub_key = settings.ocp_apim_sub_key
        self.swy_api_key = settings.swy_api_key
        self.okta_auth_server = settings.okta_auth_server
        self.okta_client_id = settings.okta_client_id
        self.ibm_client_id = settings.ibm_client_id
        self.ibm_client_secret = settings.ibm_client_secret

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None
        self._shop_token: str | None = None
        self._logger: logging.Logger | None = None

    def __enter__(self) -> Self:
        self._playwright = sync_playwright().start()
        self._browser, self._ctx, self._page = self._set_up_browser(self._playwright)
        self._log_in_with_retry()
        return self

    def _log_in_with_retry(self) -> None:
        for attempt in range(1, self.LOGIN_MAX_ATTEMPTS + 1):
            try:
                self._log_in()
                return
            except MFARequiredError:
                raise
            except Exception:
                self.logger.warning(f"Login attempt {attempt}/{self.LOGIN_MAX_ATTEMPTS} failed")
                if attempt == self.LOGIN_MAX_ATTEMPTS:
                    raise

                self.logger.warning(f"retrying in {self.LOGIN_RETRY_DELAY_SECONDS}s...")
                time.sleep(self.LOGIN_RETRY_DELAY_SECONDS)

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
        except Exception as e:
            msg = f"Non-JSON response ({resp.status}) from {resp.url}: {resp.text()[:2000]!r}"
            self.logger.debug(msg)
            raise Exception(msg) from e

    def _set_up_browser(self, p: Playwright) -> tuple[Browser, BrowserContext, Page]:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
        )
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.new_page()
        page.goto(self.root)
        page.wait_for_load_state("networkidle")

        return browser, ctx, page

    def _log_in(self) -> None:
        get_csms_headers = lambda: {  # noqa: E731
            "Accept": "application/vnd.safeway.v2+json",
            "Content-Type": "application/vnd.safeway.v2+json",
            "ocp-apim-subscription-key": self.ocp_apim_sub_key,
            "x-swy-correlation-id": str(uuid.uuid4()),
            "x-swy-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "x-swy-banner": self.banner,
            "x-swy-client-id": "web-portal",
            "x-aci-user-hash": hashlib.sha256(self.user_id.encode()).hexdigest(),
        }

        body = {"userId": self.user_id, "context": {"deviceToken": self.device_token}}

        resp = self.ctx.request.post(
            f"{self.root}/abs/pub/cnc/csmsservice/api/csms/authn",
            params={"mode": "nonotp"},
            headers=get_csms_headers(),
            data=json.dumps(body),
        )
        r: dict = self._parse_json(resp)

        try:
            okta_id = r["oktaId"]
            state_token = r["stateToken"]
        except KeyError:
            self.logger.error(f"Auth payload missing required keys: {r=}")
            raise

        body = {
            "id": okta_id,
            "passCode": self.password,
            "stateToken": state_token,
        }

        resp = self.ctx.request.post(
            f"{self.root}/abs/pub/cnc/csmsservice/api/csms/authn/factors/password/verify",
            headers=get_csms_headers(),
            data=json.dumps(body),
        )
        r = self._parse_json(resp)

        try:
            session_token: str = r["sessionToken"]
        except KeyError:
            # See if we hit an MFA check
            if r.get("status") == "MFA_REQUIRED":
                raise MFARequiredError(
                    f"MFA check required with device token '{self.device_token}'. MFA checks are not supported."
                ) from None

            self.logger.error("An unknown exception occurred and no session token was found. Response:")
            self.logger.error(r)
            raise

        if not session_token or not isinstance(session_token, str):
            raise ValueError("Invalid session token")

        # Okta redirects to this backend servlet with an auth code; the servlet exchanges
        # it server-side and responds with a Set-Cookie for SWY_SHARED_SESSION.
        authorize_url = f"{self.okta_auth_server}/v1/authorize?" + urllib.parse.urlencode(
            {
                "client_id": self.okta_client_id,
                "response_type": "code",
                "response_mode": "query",
                "scope": "openid profile email offline_access used_credentials",
                "redirect_uri": f"{self.root}/bin/safeway/unified/sso/authorize",
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
            f"{self.root}/bin/safeway/unified/userinfo",
            params={
                "rand": str(random.randint(100000, 999999)),
                "banner": self.banner,
            },
            headers={
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.root}/",
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
            f"{self.root}/abs/pub/xapi/offers/companiongalleryoffer",
            params={
                "storeId": store_id,
                "rand": str(random.randint(100000, 999999)),
                "includeRedmBonusPathFPOffers": True,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/vnd.safeway.v2+json",
                "X-SWY-APPLICATION-TYPE": "web",
                "X-SWY_API_KEY": self.swy_api_key,
                "X-SWY_VERSION": "1.1",
                "X-SWY_BANNER": self.banner,
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
            f"{self.root}/abs/pub/web/j4u/api/offers/clip",
            params={"storeId": store_id},
            headers={
                "Content-Type": "application/json",
                "SWY_SSO_TOKEN": self.shop_token,
                "X-IBM-Client-Id": self.ibm_client_id,
                "X-IBM-Client-Secret": self.ibm_client_secret,
                "X-SWY_API_KEY": self.swy_api_key,
                "X-SWY_BANNER": self.banner,
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
