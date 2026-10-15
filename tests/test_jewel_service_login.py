from collections.abc import Generator
from typing import Any

import pytest

from services import jewel_service
from services.jewel_service import JewelService, MFARequiredError
from utils import get_settings


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Generator[JewelService]:
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "4")
    get_settings.cache_clear()
    yield JewelService("user", "password", "https://www.jewelosco.com", "jewelosco", "device-token")
    get_settings.cache_clear()


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(jewel_service.time, "sleep", calls.append)
    return calls


def patch_login(monkeypatch: pytest.MonkeyPatch, service: JewelService, outcomes: list[Exception | None]) -> dict:
    """Replaces login with a stub; each login attempt consumes the next outcome (raise or succeed)."""

    counts = {"logins": 0}

    def log_in() -> None:
        outcome = outcomes[counts["logins"]]
        counts["logins"] += 1
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(service, "_log_in", log_in)
    return counts


def test_login_retries_until_success(
    monkeypatch: pytest.MonkeyPatch, service: JewelService, sleeps: list[float]
) -> None:
    counts = patch_login(monkeypatch, service, [RuntimeError("blocked"), RuntimeError("blocked"), None])

    service._log_in_with_retry()

    assert counts == {"logins": 3}
    assert sleeps == [JewelService.LOGIN_RETRY_DELAY_SECONDS] * 2


def test_login_gives_up_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch, service: JewelService, sleeps: list[float]
) -> None:
    counts = patch_login(monkeypatch, service, [RuntimeError(str(i)) for i in range(4)])

    with pytest.raises(RuntimeError, match="3"):
        service._log_in_with_retry()

    assert counts == {"logins": 4}
    assert len(sleeps) == 3


def test_login_does_not_retry_mfa(monkeypatch: pytest.MonkeyPatch, service: JewelService, sleeps: list[Any]) -> None:
    counts = patch_login(monkeypatch, service, [MFARequiredError("mfa")])

    with pytest.raises(MFARequiredError):
        service._log_in_with_retry()

    assert counts["logins"] == 1
    assert sleeps == []


def test_login_max_attempts_defaults_to_5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGIN_MAX_ATTEMPTS", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().login_max_attempts == 5
    finally:
        get_settings.cache_clear()
