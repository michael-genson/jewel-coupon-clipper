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
    """Replaces session setup/login with stubs; each login attempt consumes the next outcome (raise or succeed)."""

    counts = {"sessions": 0, "logins": 0}

    def start_session() -> None:
        counts["sessions"] += 1

    def log_in() -> None:
        outcome = outcomes[counts["logins"]]
        counts["logins"] += 1
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(service, "_start_session", start_session)
    monkeypatch.setattr(service, "_log_in", log_in)
    return counts


def test_retry_delay_backs_off_exponentially_with_jitter(service: JewelService) -> None:
    for attempt, expected in [(1, 5), (2, 10), (3, 20), (4, 40), (5, 60), (10, 60)]:
        delays = [service._get_retry_delay(attempt) for _ in range(200)]
        assert all(expected * 0.75 <= d <= expected * 1.25 for d in delays)
        assert len(set(delays)) > 1


def test_login_retries_with_fresh_session_until_success(
    monkeypatch: pytest.MonkeyPatch, service: JewelService, sleeps: list[float]
) -> None:
    counts = patch_login(monkeypatch, service, [RuntimeError("blocked"), RuntimeError("blocked"), None])

    service._log_in_with_retry()

    assert counts == {"sessions": 3, "logins": 3}
    assert len(sleeps) == 2
    assert sleeps[0] < sleeps[1]


def test_login_gives_up_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch, service: JewelService, sleeps: list[float]
) -> None:
    counts = patch_login(monkeypatch, service, [RuntimeError(str(i)) for i in range(4)])

    with pytest.raises(RuntimeError, match="3"):
        service._log_in_with_retry()

    assert counts == {"sessions": 4, "logins": 4}
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
