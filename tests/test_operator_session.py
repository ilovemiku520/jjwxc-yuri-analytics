from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from pixiv_yuri.acquisition.operator_session import (
    OperatorSessionFactory,
    RuntimeSession,
    RuntimeSessionError,
)
from pixiv_yuri.acquisition.runtime_session_lease import RuntimeSessionLeaseState
from pixiv_yuri.governance.session_cli import build_parser, main

NOW = datetime(2026, 8, 23, tzinfo=UTC)
SYNTHETIC_VALUE = "session=synthetic-operator-value"


def test_runtime_session_repr_is_redacted_and_close_zeroes_original_buffer() -> None:
    buffer = bytearray(SYNTHETIC_VALUE.encode())
    session = RuntimeSession(
        buffer,
        NOW + timedelta(minutes=5),
        established_at=NOW,
    )

    assert SYNTHETIC_VALUE not in repr(session)
    assert session.reveal_for_request(now=NOW) == SYNTHETIC_VALUE
    assert session.runtime_session_lease.state == RuntimeSessionLeaseState.CONSUMED
    with pytest.raises(RuntimeSessionError, match="unavailable"):
        session.reveal_for_request(now=NOW)
    session.close()

    assert session.closed is True
    assert set(buffer) == {0}
    with pytest.raises(RuntimeSessionError, match="closed"):
        session.reveal_for_request(now=NOW)


def test_expired_session_closes_and_zeroes_buffer() -> None:
    buffer = bytearray(SYNTHETIC_VALUE.encode())
    session = RuntimeSession(
        buffer,
        NOW,
        established_at=NOW - timedelta(minutes=5),
    )

    with pytest.raises(RuntimeSessionError, match="expired"):
        session.reveal_for_request(now=NOW)

    assert session.closed is True
    assert set(buffer) == {0}


def test_factory_uses_injected_hidden_reader_and_explicit_ttl() -> None:
    prompts: list[str] = []

    def reader(prompt: str) -> str:
        prompts.append(prompt)
        return SYNTHETIC_VALUE

    with OperatorSessionFactory(reader).open(ttl_minutes=7, now=NOW) as session:
        assert session.expires_at == NOW + timedelta(minutes=7)
        assert session.reveal_for_request(now=NOW) == SYNTHETIC_VALUE

    assert len(prompts) == 1
    assert "hidden" in prompts[0]
    assert session.closed is True


@pytest.mark.parametrize("value", ["", "session=line1\nline2", "x" * 8193])
def test_invalid_or_multiline_values_are_rejected(value: str) -> None:
    def reader(_: str) -> str:
        return value

    with pytest.raises(RuntimeSessionError, match="invalid"):
        OperatorSessionFactory(reader).open(ttl_minutes=5, now=NOW)


def test_cli_has_no_session_secret_command_line_option() -> None:
    option_strings = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    assert all(
        fragment not in option.lower()
        for option in option_strings
        for fragment in ("cookie", "password", "secret", "token", "session-value")
    )


def test_dry_run_cli_prints_only_safe_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["--dry-run", "--session-ttl-minutes", "5"],
        reader=lambda _: SYNTHETIC_VALUE,
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["external_network_used"] is False
    assert payload["session_persisted"] is False
    assert payload["session_logged"] is False
    assert SYNTHETIC_VALUE not in output
