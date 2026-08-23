"""One-use operator confirmation gate for a dry-run first request."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

MIN_CONFIRMATION_TTL_SECONDS = 5
MAX_CONFIRMATION_TTL_SECONDS = 120


class ConfirmationGateError(RuntimeError):
    """A safe, non-secret gate failure."""


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Safe fields suitable for console output and an offline report."""

    status: str
    mode: str
    planned_requests: int
    issued_at: str | None
    expires_at: str | None
    confirmed_at: str | None
    challenge_consumed: bool
    external_network_used: bool
    violations: tuple[str, ...]


class OneUseConfirmation:
    """Hold only a challenge digest and burn the challenge on the first attempt."""

    __slots__ = ("_consumed", "_digest", "_expires_at", "_issued_at")

    def __init__(
        self,
        phrase: str,
        *,
        issued_at: datetime,
        ttl_seconds: int,
    ) -> None:
        _validate_aware(issued_at, "Confirmation issue time")
        _validate_ttl(ttl_seconds)
        if not phrase or "\r" in phrase or "\n" in phrase:
            raise ValueError("Confirmation phrase is invalid.")
        self._digest = _phrase_digest(phrase)
        self._issued_at = issued_at.astimezone(UTC)
        self._expires_at = self._issued_at + timedelta(seconds=ttl_seconds)
        self._consumed = False

    @property
    def issued_at(self) -> datetime:
        return self._issued_at

    @property
    def expires_at(self) -> datetime:
        return self._expires_at

    @property
    def consumed(self) -> bool:
        return self._consumed

    def confirm(self, candidate: str, *, now: datetime | None = None) -> bool:
        """Consume exactly once, even when the phrase is wrong or expired."""
        checked_at = now or datetime.now(UTC)
        _validate_aware(checked_at, "Confirmation time")
        if self._consumed:
            raise ConfirmationGateError("Confirmation challenge was already consumed.")
        self._consumed = True
        if checked_at.astimezone(UTC) >= self._expires_at:
            return False
        if not candidate or "\r" in candidate or "\n" in candidate:
            return False
        return hmac.compare_digest(self._digest, _phrase_digest(candidate.strip()))


def run_confirmation_gate(
    *,
    planned_requests: int,
    ttl_seconds: int,
    reader: Callable[[str], str],
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> ConfirmationResult:
    """Require an in-process operator confirmation; never initiate transport."""
    if planned_requests != 1:
        return _blocked(planned_requests, "planned_requests_must_equal_one")
    try:
        _validate_ttl(ttl_seconds)
    except ValueError:
        return _blocked(planned_requests, "confirmation_ttl_out_of_range")

    clock = now or (lambda: datetime.now(UTC))
    issued_at = clock()
    _validate_aware(issued_at, "Confirmation issue time")
    phrase = (phrase_factory or _new_phrase)()
    challenge = OneUseConfirmation(
        phrase,
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
    )
    try:
        candidate = reader(
            "Dry-run only. Type this one-use phrase to confirm exactly one planned request: "
            f"{phrase}\nConfirmation: "
        )
    except (EOFError, KeyboardInterrupt):
        candidate = ""
    finally:
        phrase = ""

    confirmed_at = clock()
    _validate_aware(confirmed_at, "Confirmation time")
    accepted = challenge.confirm(candidate, now=confirmed_at)
    candidate = ""
    violations = () if accepted else ("operator_confirmation_missing_or_invalid",)
    return ConfirmationResult(
        status="passed" if accepted else "blocked",
        mode="dry_run",
        planned_requests=1,
        issued_at=challenge.issued_at.isoformat(),
        expires_at=challenge.expires_at.isoformat(),
        confirmed_at=confirmed_at.astimezone(UTC).isoformat() if accepted else None,
        challenge_consumed=challenge.consumed,
        external_network_used=False,
        violations=violations,
    )


def build_parser() -> argparse.ArgumentParser:
    """Expose only non-secret gate settings and an optional report destination."""
    parser = argparse.ArgumentParser(prog="pyuri-first-request-gate")
    parser.add_argument("--planned-requests", type=int, default=1)
    parser.add_argument("--confirmation-ttl-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    reader: Callable[[str], str] | None = None,
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Run the dry-run-only gate and print/write only safe result fields."""
    args = build_parser().parse_args(argv)
    result = run_confirmation_gate(
        planned_requests=args.planned_requests,
        ttl_seconds=args.confirmation_ttl_seconds,
        reader=reader or input,
        phrase_factory=phrase_factory,
        now=now,
    )
    payload = asdict(result)
    _write_payload(args.output, payload)
    stream = sys.stdout if result.status == "passed" else sys.stderr
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)
    return 0 if result.status == "passed" else 2


def _new_phrase() -> str:
    return f"CONFIRM-ONE-{secrets.token_hex(6).upper()}"


def _phrase_digest(phrase: str) -> bytes:
    return hashlib.sha256(phrase.encode("utf-8")).digest()


def _validate_ttl(ttl_seconds: int) -> None:
    if not MIN_CONFIRMATION_TTL_SECONDS <= ttl_seconds <= MAX_CONFIRMATION_TTL_SECONDS:
        raise ValueError(
            "Confirmation TTL must be between "
            f"{MIN_CONFIRMATION_TTL_SECONDS} and {MAX_CONFIRMATION_TTL_SECONDS} seconds."
        )


def _validate_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone.")


def _blocked(planned_requests: int, violation: str) -> ConfirmationResult:
    return ConfirmationResult(
        status="blocked",
        mode="dry_run",
        planned_requests=planned_requests,
        issued_at=None,
        expires_at=None,
        confirmed_at=None,
        challenge_consumed=False,
        external_network_used=False,
        violations=(violation,),
    )


def _write_payload(output: Path | None, payload: dict[str, object]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
