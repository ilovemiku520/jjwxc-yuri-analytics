from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from pixiv_yuri.governance import first_request_gate
from pixiv_yuri.governance.first_request_gate import (
    ConfirmationGateError,
    OneUseConfirmation,
    build_parser,
    main,
    run_confirmation_gate,
)

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
PHRASE = "CONFIRM-ONE-001122AABBCC"


def test_valid_phrase_authorizes_only_a_dry_run() -> None:
    result = run_confirmation_gate(
        planned_requests=1,
        ttl_seconds=30,
        reader=lambda prompt: PHRASE if PHRASE in prompt else "",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.status == "passed"
    assert result.mode == "dry_run"
    assert result.planned_requests == 1
    assert result.challenge_consumed is True
    assert result.external_network_used is False
    assert result.violations == ()


@pytest.mark.parametrize("planned_requests", [0, 2, 25])
def test_planned_requests_must_equal_one_without_issuing_challenge(
    planned_requests: int,
) -> None:
    reader_called = False

    def reader(_: str) -> str:
        nonlocal reader_called
        reader_called = True
        return PHRASE

    result = run_confirmation_gate(
        planned_requests=planned_requests,
        ttl_seconds=30,
        reader=reader,
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.status == "blocked"
    assert result.violations == ("planned_requests_must_equal_one",)
    assert result.challenge_consumed is False
    assert reader_called is False


def test_confirmation_is_burned_after_wrong_first_attempt() -> None:
    challenge = OneUseConfirmation(PHRASE, issued_at=NOW, ttl_seconds=30)

    assert challenge.confirm("wrong", now=NOW) is False
    with pytest.raises(ConfirmationGateError, match="already consumed"):
        challenge.confirm(PHRASE, now=NOW)


def test_expired_confirmation_is_burned_and_cannot_be_reused() -> None:
    challenge = OneUseConfirmation(PHRASE, issued_at=NOW, ttl_seconds=5)

    assert challenge.confirm(PHRASE, now=NOW + timedelta(seconds=5)) is False
    assert challenge.consumed is True
    with pytest.raises(ConfirmationGateError, match="already consumed"):
        challenge.confirm(PHRASE, now=NOW + timedelta(seconds=6))


def test_missing_confirmation_fails_closed() -> None:
    result = run_confirmation_gate(
        planned_requests=1,
        ttl_seconds=30,
        reader=lambda _: "",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.status == "blocked"
    assert result.confirmed_at is None
    assert result.violations == ("operator_confirmation_missing_or_invalid",)
    assert result.challenge_consumed is True


def test_cli_has_no_credential_or_confirmation_value_option() -> None:
    option_strings = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    forbidden = ("password", "cookie", "token", "secret", "session", "confirmation-value")
    assert all(
        fragment not in option.lower()
        for option in option_strings
        for fragment in forbidden
    )


def test_cli_writes_only_safe_fields_and_never_the_phrase(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: dict[str, object] = {}

    def capture_payload(_output: object, payload: dict[str, object]) -> None:
        written.update(payload)

    monkeypatch.setattr(first_request_gate, "_write_payload", capture_payload)
    exit_code = main(
        ["--output", "ignored-test-report.json"],
        reader=lambda _: PHRASE,
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )
    console = capsys.readouterr().out
    serialized = json.dumps(written, sort_keys=True)

    assert exit_code == 0
    assert PHRASE not in console
    assert PHRASE not in serialized
    assert written["external_network_used"] is False
    assert set(written) == {
        "status",
        "mode",
        "planned_requests",
        "issued_at",
        "expires_at",
        "confirmed_at",
        "challenge_consumed",
        "external_network_used",
        "violations",
    }


def test_cli_default_is_dry_run_and_rejection_exit_is_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [],
        reader=lambda _: "no",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert payload["mode"] == "dry_run"
    assert payload["status"] == "blocked"
    assert payload["external_network_used"] is False
