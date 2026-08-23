from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from pixiv_yuri.acquisition.browser_export_import import (
    sanitize_browser_export_batch,
    sanitize_browser_export_json,
    sanitize_powerful_pixiv_json,
    sanitize_pyuri_browser_companion_json,
)


def _record(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "index": 0,
        "idNum": 123456,
        "title": "Synthetic work",
        "userId": "789",
        "user": "Synthetic author",
        "tags": ["百合", "創作"],
        "tagsTranslOnly": ["Yuri", "Original"],
        "date": "2026-08-23T00:00:00+09:00",
        "pageCount": 1,
        "fullWidth": 1200,
        "fullHeight": 900,
        "viewCount": 10,
        "bmk": 2,
        "likeCount": 3,
        "xRestrict": 0,
        "novelMeta": None,
        "original": "https://media.invalid/original.jpg",
        "thumb": "https://media.invalid/thumb.jpg",
        "description": "not allowlisted",
        "bookmarked": True,
    }
    value.update(changes)
    return value


def _bytes(records: list[object]) -> bytes:
    return json.dumps(records, ensure_ascii=False).encode()


def _companion_record(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "work_id": "123456",
        "work_title": "Synthetic work",
        "author_id": "789",
        "author_display_name": "Synthetic author",
        "public_tags": [
            {"tag_name": "百合", "tag_translation": "Yuri"},
            {"tag_name": "創作", "tag_translation": None},
        ],
        "created_at": "2026-08-23T00:00:00+09:00",
        "page_count": 1,
        "width": 1200,
        "height": 900,
        "public_view_count": 10,
        "public_bookmark_count": 2,
        "public_like_count": 3,
        "x_restrict": 0,
    }
    value.update(changes)
    return value


def _companion_bytes(records: list[object], **changes: object) -> bytes:
    value: dict[str, object] = {
        "source_format": "pyuri_pixiv_browser_companion_json",
        "schema_version": 1,
        "generated_at": "2026-08-23T00:00:00Z",
        "records": records,
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False).encode()


def test_sanitizes_allowlist_and_never_emits_media_or_user_state() -> None:
    records, report = sanitize_powerful_pixiv_json(
        _bytes([_record()]), now=datetime(2026, 8, 23, tzinfo=UTC)
    )

    assert report.status == "candidate_ready"
    assert report.accepted_records == 1
    assert report.visibility_verified is False
    assert report.canonical_ingest_authorized is False
    assert report.credentials_requested is False
    assert report.external_network_used is False
    assert report.media_persisted is False
    assert report.raw_payload_persisted is False
    output = records[0].model_dump(mode="json")
    assert set(output) == {
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
    }
    assert "media.invalid" not in json.dumps(output)
    assert output["created_at"] == "2026-08-22T15:00:00Z"


def test_rejects_r18_r18g_and_unknown_rating() -> None:
    records, report = sanitize_powerful_pixiv_json(
        _bytes(
            [
                _record(xRestrict=1),
                _record(idNum=2, xRestrict=2),
                _record(idNum=3, xRestrict=None),
            ]
        )
    )

    assert records == []
    assert report.status == "blocked"
    assert report.rejected_records == 3
    assert report.violations == ("age_rating_not_proven_all_ages",)


def test_rejects_novel_body_and_skips_extra_pages_and_duplicates() -> None:
    records, report = sanitize_powerful_pixiv_json(
        _bytes(
            [
                _record(novelMeta={"content": "forbidden"}),
                _record(idNum=2, index=1),
                _record(idNum=3),
                _record(idNum=3),
            ]
        )
    )

    assert [record.work_id for record in records] == ["3"]
    assert report.rejected_records == 1
    assert report.duplicate_or_extra_page_records == 2
    assert "novel_body_forbidden" in report.violations


def test_malformed_or_oversized_export_is_blocked() -> None:
    records, report = sanitize_powerful_pixiv_json(b"not-json")
    assert records == []
    assert report.violations == ("invalid_json",)

    records, report = sanitize_powerful_pixiv_json(b"[]" + b" " * 10_000_000)
    assert records == []
    assert report.violations == ("export_too_large",)


def test_secret_or_unknown_source_fields_block_without_echoing_values() -> None:
    records, report = sanitize_powerful_pixiv_json(
        _bytes([_record(sessionToken="do-not-echo")])
    )
    assert records == []
    assert report.violations == ("secret_shaped_field_forbidden",)
    assert "do-not-echo" not in json.dumps(asdict(report))

    records, report = sanitize_powerful_pixiv_json(_bytes([_record(newVendorField=True)]))
    assert records == []
    assert report.violations == ("unsupported_source_field",)


def test_companion_accepts_all_g0_ratings_and_drops_the_rating_field() -> None:
    records, report = sanitize_pyuri_browser_companion_json(
        _companion_bytes(
            [
                _companion_record(),
                _companion_record(work_id="2", x_restrict=1),
                _companion_record(work_id="3", x_restrict=2),
            ]
        ),
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert report.status == "candidate_ready"
    assert report.source_format == "pyuri_pixiv_browser_companion_json"
    assert report.accepted_records == 3
    assert report.visibility_verified is False
    assert report.canonical_ingest_authorized is False
    assert [record.work_id for record in records] == ["123456", "2", "3"]
    assert all("x_restrict" not in record.model_dump(mode="json") for record in records)


def test_companion_blocks_unknown_fields_secrets_and_unapproved_ratings() -> None:
    records, report = sanitize_pyuri_browser_companion_json(
        _companion_bytes([_companion_record(x_restrict=3)])
    )
    assert records == []
    assert report.violations == ("age_rating_outside_g0",)

    records, report = sanitize_pyuri_browser_companion_json(
        _companion_bytes([_companion_record()], password="do-not-echo")
    )
    assert records == []
    assert report.violations == ("secret_shaped_field_forbidden",)
    assert "do-not-echo" not in json.dumps(asdict(report))

    records, report = sanitize_pyuri_browser_companion_json(
        _companion_bytes([_companion_record()], unknown=True)
    )
    assert records == []
    assert report.violations == ("unsupported_root_field",)


def test_browser_export_dispatches_companion_and_ppd_shapes() -> None:
    records, report = sanitize_browser_export_json(_companion_bytes([_companion_record()]))
    assert len(records) == 1
    assert report.source_format == "pyuri_pixiv_browser_companion_json"

    records, report = sanitize_browser_export_json(_bytes([_record()]))
    assert len(records) == 1
    assert report.source_format == "powerful_pixiv_downloader_json"


def test_batch_deduplicates_across_companion_files_without_weakening_boundaries() -> None:
    records, report = sanitize_browser_export_batch(
        [
            _companion_bytes([_companion_record()]),
            _companion_bytes(
                [
                    _companion_record(),
                    _companion_record(work_id="2", x_restrict=2),
                ]
            ),
        ],
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert [record.work_id for record in records] == ["123456", "2"]
    assert report.status == "candidate_ready"
    assert report.input_files == 2
    assert report.input_records == 3
    assert report.accepted_records == 2
    assert report.duplicate_or_extra_page_records == 1
    assert report.external_network_used is False
    assert report.canonical_ingest_authorized is False


def test_batch_blocks_mixed_formats_or_any_invalid_file() -> None:
    records, report = sanitize_browser_export_batch(
        [_companion_bytes([_companion_record()]), _bytes([_record()])]
    )
    assert len(records) == 1
    assert report.duplicate_or_extra_page_records == 1
    assert report.status == "blocked"
    assert report.violations == ("mixed_source_formats_forbidden",)

    records, report = sanitize_browser_export_batch(
        [_companion_bytes([_companion_record()]), b"not-json"]
    )
    assert len(records) == 1
    assert report.status == "blocked"
    assert "invalid_json" in report.violations
