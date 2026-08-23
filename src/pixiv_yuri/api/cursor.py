"""Versioned, tamper-evident opaque cursors for read-only keyset pagination."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct

_VERSION = 1
_PAYLOAD_SIZE = 9
_CHECKSUM_SIZE = 6
_TOKEN_SIZE = _PAYLOAD_SIZE + _CHECKSUM_SIZE
_DOMAIN = b"pixiv-yuri-read-cursor-v1\x00"
_RANK_VERSION = 2
_RANK_PAYLOAD_SIZE = 21
_RANK_TOKEN_SIZE = _RANK_PAYLOAD_SIZE + _CHECKSUM_SIZE


class InvalidCursorError(ValueError):
    """Raised when a cursor is malformed, unsupported, or corrupted."""


def encode_cursor(row_id: int) -> str:
    """Encode a positive database key without exposing a mutable query contract."""
    if row_id <= 0:
        raise ValueError("row_id must be positive")
    payload = bytes((_VERSION,)) + struct.pack(">Q", row_id)
    checksum = hashlib.sha256(_DOMAIN + payload).digest()[:_CHECKSUM_SIZE]
    return base64.urlsafe_b64encode(payload + checksum).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str | None) -> int:
    """Decode and verify a cursor; an absent cursor starts at key zero."""
    if cursor is None:
        return 0
    if not cursor or len(cursor) > 64 or not cursor.isascii():
        raise InvalidCursorError("invalid cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        token = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if len(token) != _TOKEN_SIZE:
        raise InvalidCursorError("invalid cursor")
    payload, checksum = token[:_PAYLOAD_SIZE], token[_PAYLOAD_SIZE:]
    expected = hashlib.sha256(_DOMAIN + payload).digest()[:_CHECKSUM_SIZE]
    if payload[0] != _VERSION or not hmac.compare_digest(checksum, expected):
        raise InvalidCursorError("invalid cursor")
    row_id = struct.unpack(">Q", payload[1:])[0]
    if row_id <= 0:
        raise InvalidCursorError("invalid cursor")
    return int(row_id)


def encode_rank_cursor(score: int, row_id: int, namespace: str) -> str:
    """Bind a descending score and ascending key to one ranking namespace."""
    if score < 0 or row_id <= 0:
        raise ValueError("score must be nonnegative and row_id must be positive")
    namespace_hash = _namespace_hash(namespace)
    payload = (
        bytes((_RANK_VERSION,))
        + struct.pack(">Q", score)
        + struct.pack(">Q", row_id)
        + namespace_hash
    )
    checksum = hashlib.sha256(_DOMAIN + payload).digest()[:_CHECKSUM_SIZE]
    return base64.urlsafe_b64encode(payload + checksum).rstrip(b"=").decode("ascii")


def decode_rank_cursor(cursor: str | None, namespace: str) -> tuple[int, int] | None:
    """Decode a namespace-bound ranking cursor or return the first-page sentinel."""
    if cursor is None:
        return None
    if not cursor or len(cursor) > 80 or not cursor.isascii():
        raise InvalidCursorError("invalid cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        token = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if len(token) != _RANK_TOKEN_SIZE:
        raise InvalidCursorError("invalid cursor")
    payload, checksum = token[:_RANK_PAYLOAD_SIZE], token[_RANK_PAYLOAD_SIZE:]
    expected = hashlib.sha256(_DOMAIN + payload).digest()[:_CHECKSUM_SIZE]
    if (
        payload[0] != _RANK_VERSION
        or not hmac.compare_digest(checksum, expected)
        or not hmac.compare_digest(payload[17:], _namespace_hash(namespace))
    ):
        raise InvalidCursorError("invalid cursor")
    score = int(struct.unpack(">Q", payload[1:9])[0])
    row_id = int(struct.unpack(">Q", payload[9:17])[0])
    if row_id <= 0:
        raise InvalidCursorError("invalid cursor")
    return score, row_id


def _namespace_hash(namespace: str) -> bytes:
    if not namespace or len(namespace) > 64 or not namespace.isascii():
        raise ValueError("cursor namespace must be 1-64 ASCII characters")
    return hashlib.sha256(namespace.encode("ascii")).digest()[:4]
