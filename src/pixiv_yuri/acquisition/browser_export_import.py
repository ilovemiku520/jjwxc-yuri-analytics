"""Sanitize a user-created browser export without using network or credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_EXPORT_BYTES = 10_000_000
MAX_EXPORT_RECORDS = 1_000
MAX_COMPANION_RECORDS = 25
MAX_BATCH_FILES = 25
MAX_BATCH_BYTES = 10_000_000
_SECRET_KEYS = frozenset(
    {"authorization", "cookie", "credential", "password", "secret", "session", "token"}
)
_SUPPORTED_SOURCE_KEYS = frozenset(
    {
        "aiType",
        "bmk",
        "bmkId",
        "bookmarked",
        "commentCount",
        "date",
        "description",
        "ext",
        "fullHeight",
        "fullWidth",
        "id",
        "idNum",
        "index",
        "isOriginal",
        "likeCount",
        "novelMeta",
        "original",
        "pageCount",
        "rank",
        "regular",
        "seriesId",
        "seriesOrder",
        "seriesTitle",
        "sl",
        "small",
        "tags",
        "tagsTranslOnly",
        "tagsWithTransl",
        "thumb",
        "title",
        "type",
        "ugoiraInfo",
        "uploadDate",
        "user",
        "userId",
        "viewCount",
        "xRestrict",
    }
)
_COMPANION_SOURCE_FORMAT = "pyuri_pixiv_browser_companion_json"
_COMPANION_ROOT_KEYS = frozenset(
    {"source_format", "schema_version", "generated_at", "records"}
)
_COMPANION_RECORD_KEYS = frozenset(
    {
        "work_id",
        "work_title",
        "author_id",
        "author_display_name",
        "public_tags",
        "created_at",
        "page_count",
        "width",
        "height",
        "public_view_count",
        "public_bookmark_count",
        "public_like_count",
        "x_restrict",
    }
)
_COMPANION_TAG_KEYS = frozenset({"tag_name", "tag_translation"})
_G0_ALLOWED_X_RESTRICT = frozenset({0, 1, 2})


class PublicTag(BaseModel):
    """One allowlisted public tag and its optional display translation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    tag_name: str = Field(min_length=1, max_length=200)
    tag_translation: str | None = Field(default=None, max_length=200)


class SanitizedPublicMetadata(BaseModel):
    """The exact field-only shape permitted by the public metadata policy."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    work_id: str = Field(min_length=1, max_length=64)
    work_title: str = Field(max_length=500)
    author_id: str = Field(min_length=1, max_length=64)
    author_display_name: str = Field(max_length=200)
    public_tags: list[PublicTag] = Field(max_length=10)
    created_at: datetime
    page_count: int = Field(ge=1, le=10_000)
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    public_view_count: int | None = Field(default=None, ge=0)
    public_bookmark_count: int | None = Field(default=None, ge=0)
    public_like_count: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class BrowserExportImportReport:
    """Value-free audit evidence for a local-only sanitization run."""

    generated_at: str
    status: str
    source_format: str
    input_sha256: str
    input_files: int
    input_records: int
    accepted_records: int
    rejected_records: int
    duplicate_or_extra_page_records: int
    violations: tuple[str, ...]
    visibility_verified: bool
    canonical_ingest_authorized: bool
    credentials_requested: bool
    external_network_used: bool
    media_persisted: bool
    raw_payload_persisted: bool


def sanitize_powerful_pixiv_json(
    data: bytes,
    *,
    now: datetime | None = None,
) -> tuple[list[SanitizedPublicMetadata], BrowserExportImportReport]:
    """Convert Powerful Pixiv Downloader JSON into candidate metadata only.

    The source format has media URLs and user-state fields. They are intentionally
    ignored. Records whose all-ages status cannot be proved are rejected. The
    exporter does not prove public visibility, so output remains non-canonical.
    """
    generated_at = _aware_utc(now or datetime.now(UTC)).isoformat()
    input_hash = hashlib.sha256(data).hexdigest()
    violations: list[str] = []
    accepted: list[SanitizedPublicMetadata] = []
    rejected = 0
    skipped = 0

    if len(data) > MAX_EXPORT_BYTES:
        return [], _report(
            generated_at, input_hash, 0, 0, 0, 0, ("export_too_large",)
        )
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], _report(generated_at, input_hash, 0, 0, 0, 0, ("invalid_json",))
    if not isinstance(payload, list):
        return [], _report(
            generated_at, input_hash, 0, 0, 0, 0, ("root_must_be_array",)
        )
    if _contains_secret_key(payload):
        return [], _report(
            generated_at,
            input_hash,
            len(payload),
            0,
            len(payload),
            0,
            ("secret_shaped_field_forbidden",),
        )
    if len(payload) > MAX_EXPORT_RECORDS:
        return [], _report(
            generated_at,
            input_hash,
            len(payload),
            0,
            len(payload),
            0,
            ("too_many_records",),
        )

    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, Mapping):
            rejected += 1
            violations.append("record_not_object")
            continue
        index = item.get("index")
        if index not in (None, 0):
            skipped += 1
            continue
        try:
            record = _sanitize_record(item)
        except (TypeError, ValueError, ValidationError) as error:
            rejected += 1
            violations.append(_safe_reason(error))
            continue
        if record.work_id in seen:
            skipped += 1
            continue
        seen.add(record.work_id)
        accepted.append(record)

    return accepted, _report(
        generated_at,
        input_hash,
        len(payload),
        len(accepted),
        rejected,
        skipped,
        tuple(dict.fromkeys(violations)),
    )


def sanitize_pyuri_browser_companion_json(
    data: bytes,
    *,
    now: datetime | None = None,
) -> tuple[list[SanitizedPublicMetadata], BrowserExportImportReport]:
    """Validate the project's user-triggered current-page browser export.

    The companion does not prove public visibility and never grants canonical ingest.
    Ratings 0, 1 and 2 are accepted because the active G0 explicitly permits
    all-ages, R-18 and R-18G metadata while prohibiting media and private content.
    """
    generated_at = _aware_utc(now or datetime.now(UTC)).isoformat()
    input_hash = hashlib.sha256(data).hexdigest()
    if len(data) > MAX_EXPORT_BYTES:
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("export_too_large",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("invalid_json",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    if not isinstance(payload, Mapping):
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("root_must_be_object",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    if _contains_secret_key(payload):
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("secret_shaped_field_forbidden",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    if any(str(key) not in _COMPANION_ROOT_KEYS for key in payload):
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("unsupported_root_field",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    if payload.get("source_format") != _COMPANION_SOURCE_FORMAT:
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("unsupported_source_format",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    if payload.get("schema_version") != 1:
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("unsupported_schema_version",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    try:
        _datetime(payload.get("generated_at"))
    except ValueError:
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("generated_at_invalid",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    source_records = payload.get("records")
    if not isinstance(source_records, list):
        return [], _report(
            generated_at,
            input_hash,
            0,
            0,
            0,
            0,
            ("records_must_be_array",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )
    if len(source_records) > MAX_COMPANION_RECORDS:
        return [], _report(
            generated_at,
            input_hash,
            len(source_records),
            0,
            len(source_records),
            0,
            ("too_many_records",),
            source_format=_COMPANION_SOURCE_FORMAT,
        )

    accepted: list[SanitizedPublicMetadata] = []
    violations: list[str] = []
    rejected = 0
    skipped = 0
    seen: set[str] = set()
    for item in source_records:
        if not isinstance(item, Mapping):
            rejected += 1
            violations.append("record_not_object")
            continue
        try:
            record = _sanitize_companion_record(item)
        except (TypeError, ValueError, ValidationError) as error:
            rejected += 1
            violations.append(_safe_reason(error))
            continue
        if record.work_id in seen:
            skipped += 1
            continue
        seen.add(record.work_id)
        accepted.append(record)

    return accepted, _report(
        generated_at,
        input_hash,
        len(source_records),
        len(accepted),
        rejected,
        skipped,
        tuple(dict.fromkeys(violations)),
        source_format=_COMPANION_SOURCE_FORMAT,
    )


def sanitize_browser_export_json(
    data: bytes,
    *,
    now: datetime | None = None,
) -> tuple[list[SanitizedPublicMetadata], BrowserExportImportReport]:
    """Dispatch a supported browser export without interpreting unknown objects."""
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return sanitize_powerful_pixiv_json(data, now=now)
    if isinstance(payload, Mapping):
        return sanitize_pyuri_browser_companion_json(data, now=now)
    return sanitize_powerful_pixiv_json(data, now=now)


def sanitize_browser_export_batch(
    exports: Sequence[bytes],
    *,
    now: datetime | None = None,
) -> tuple[list[SanitizedPublicMetadata], BrowserExportImportReport]:
    """Sanitize and deduplicate a bounded set of same-format browser exports."""
    checked_at = _aware_utc(now or datetime.now(UTC))
    generated_at = checked_at.isoformat()
    if not exports or len(exports) > MAX_BATCH_FILES:
        return [], _report(
            generated_at,
            _batch_hash(exports),
            0,
            0,
            0,
            0,
            ("batch_file_count_out_of_range",),
            input_files=len(exports),
        )
    if sum(len(data) for data in exports) > MAX_BATCH_BYTES:
        return [], _report(
            generated_at,
            _batch_hash(exports),
            0,
            0,
            0,
            0,
            ("export_batch_too_large",),
            input_files=len(exports),
        )
    if len(exports) == 1:
        return sanitize_browser_export_json(exports[0], now=checked_at)

    accepted: list[SanitizedPublicMetadata] = []
    seen: set[str] = set()
    formats: list[str] = []
    violations: list[str] = []
    input_records = 0
    rejected = 0
    skipped = 0
    for data in exports:
        records, report = sanitize_browser_export_json(data, now=checked_at)
        formats.append(report.source_format)
        input_records += report.input_records
        rejected += report.rejected_records
        skipped += report.duplicate_or_extra_page_records
        violations.extend(report.violations)
        for record in records:
            if record.work_id in seen:
                skipped += 1
                continue
            seen.add(record.work_id)
            accepted.append(record)
    source_format = formats[0]
    if any(value != source_format for value in formats[1:]):
        violations.append("mixed_source_formats_forbidden")
    return accepted, _report(
        generated_at,
        _batch_hash(exports),
        input_records,
        len(accepted),
        rejected,
        skipped,
        tuple(dict.fromkeys(violations)),
        source_format=source_format,
        input_files=len(exports),
    )


def _batch_hash(exports: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for data in exports:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _sanitize_record(item: Mapping[str, Any]) -> SanitizedPublicMetadata:
    if any(str(key) not in _SUPPORTED_SOURCE_KEYS for key in item):
        raise ValueError("unsupported_source_field")
    if type(item.get("xRestrict")) is not int or item["xRestrict"] != 0:
        raise ValueError("age_rating_not_proven_all_ages")
    if item.get("novelMeta") not in (None,):
        raise ValueError("novel_body_forbidden")

    work_id = item.get("idNum")
    if type(work_id) is not int or work_id <= 0:
        raise ValueError("work_id_invalid")
    tags = _string_list(item.get("tags"), "tags_invalid")[:10]
    translations = _optional_string_list(item.get("tagsTranslOnly"))
    public_tags = [
        PublicTag(
            tag_name=tag,
            tag_translation=(
                translations[index]
                if index < len(translations) and translations[index] not in ("", tag)
                else None
            ),
        )
        for index, tag in enumerate(tags)
    ]

    return SanitizedPublicMetadata(
        work_id=str(work_id),
        work_title=_string(item.get("title"), "title_invalid"),
        author_id=_string(item.get("userId"), "author_id_invalid"),
        author_display_name=_string(item.get("user"), "author_name_invalid"),
        public_tags=public_tags,
        created_at=_datetime(item.get("date")),
        page_count=_integer(item.get("pageCount"), "page_count_invalid"),
        width=_integer(item.get("fullWidth"), "width_invalid"),
        height=_integer(item.get("fullHeight"), "height_invalid"),
        public_view_count=_optional_integer(item.get("viewCount"), "view_count_invalid"),
        public_bookmark_count=_optional_integer(item.get("bmk"), "bookmark_count_invalid"),
        public_like_count=_optional_integer(item.get("likeCount"), "like_count_invalid"),
    )


def _sanitize_companion_record(item: Mapping[str, Any]) -> SanitizedPublicMetadata:
    if any(str(key) not in _COMPANION_RECORD_KEYS for key in item):
        raise ValueError("unsupported_source_field")
    rating = item.get("x_restrict")
    if type(rating) is not int or rating not in _G0_ALLOWED_X_RESTRICT:
        raise ValueError("age_rating_outside_g0")
    source_tags = item.get("public_tags")
    if not isinstance(source_tags, list):
        raise ValueError("tags_invalid")
    public_tags: list[PublicTag] = []
    for tag in source_tags:
        if not isinstance(tag, Mapping) or any(
            str(key) not in _COMPANION_TAG_KEYS for key in tag
        ):
            raise ValueError("tags_invalid")
        translation = tag.get("tag_translation")
        if translation is not None and not isinstance(translation, str):
            raise ValueError("tag_translations_invalid")
        public_tags.append(
            PublicTag(
                tag_name=_string(tag.get("tag_name"), "tags_invalid"),
                tag_translation=translation,
            )
        )

    return SanitizedPublicMetadata(
        work_id=_string(item.get("work_id"), "work_id_invalid"),
        work_title=_string(item.get("work_title"), "title_invalid"),
        author_id=_string(item.get("author_id"), "author_id_invalid"),
        author_display_name=_string(
            item.get("author_display_name"), "author_name_invalid"
        ),
        public_tags=public_tags,
        created_at=_datetime(item.get("created_at")),
        page_count=_integer(item.get("page_count"), "page_count_invalid"),
        width=_integer(item.get("width"), "width_invalid"),
        height=_integer(item.get("height"), "height_invalid"),
        public_view_count=_optional_integer(
            item.get("public_view_count"), "view_count_invalid"
        ),
        public_bookmark_count=_optional_integer(
            item.get("public_bookmark_count"), "bookmark_count_invalid"
        ),
        public_like_count=_optional_integer(
            item.get("public_like_count"), "like_count_invalid"
        ),
    )


def _string(value: object, reason: str) -> str:
    if not isinstance(value, str):
        raise ValueError(reason)
    return value


def _integer(value: object, reason: str) -> int:
    if type(value) is not int:
        raise ValueError(reason)
    return value


def _optional_integer(value: object, reason: str) -> int | None:
    if value is None:
        return None
    return _integer(value, reason)


def _string_list(value: object, reason: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(reason)
    return value


def _optional_string_list(value: object) -> list[str]:
    if value is None:
        return []
    return _string_list(value, "tag_translations_invalid")


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("created_at_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_timezone_required")
    return value.astimezone(UTC)


def _safe_reason(error: Exception) -> str:
    if isinstance(error, ValueError) and error.args and isinstance(error.args[0], str):
        candidate = error.args[0]
        if candidate.replace("_", "").isalnum() and len(candidate) <= 80:
            return candidate
    return "normalized_schema_validation_failed"


def _contains_secret_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _SECRET_KEYS):
                return True
            if _contains_secret_key(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_secret_key(child) for child in value)
    return False


def _report(
    generated_at: str,
    input_hash: str,
    input_records: int,
    accepted: int,
    rejected: int,
    skipped: int,
    violations: tuple[str, ...],
    *,
    source_format: str = "powerful_pixiv_downloader_json",
    input_files: int = 1,
) -> BrowserExportImportReport:
    return BrowserExportImportReport(
        generated_at=generated_at,
        status="candidate_ready" if accepted and not rejected and not violations else "blocked",
        source_format=source_format,
        input_sha256=input_hash,
        input_files=input_files,
        input_records=input_records,
        accepted_records=accepted,
        rejected_records=rejected,
        duplicate_or_extra_page_records=skipped,
        violations=violations,
        visibility_verified=False,
        canonical_ingest_authorized=False,
        credentials_requested=False,
        external_network_used=False,
        media_persisted=False,
        raw_payload_persisted=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", nargs="+", type=Path, help="User-exported JSON files (read only)."
    )
    parser.add_argument("--output", type=Path, required=True, help="Sanitized JSONL output.")
    parser.add_argument("--report", type=Path, required=True, help="Value-free audit report.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if (args.output.exists() or args.report.exists()) and not args.force:
        print("output_exists", file=sys.stderr)
        return 2
    try:
        inputs = [path.read_bytes() for path in args.input]
    except OSError:
        print("input_unreadable", file=sys.stderr)
        return 2

    records, report = sanitize_browser_export_batch(inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    output_records = records if report.status == "candidate_ready" else []
    args.output.write_text(
        "".join(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for record in output_records
        ),
        encoding="utf-8",
    )
    args.report.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return 0 if report.status == "candidate_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
