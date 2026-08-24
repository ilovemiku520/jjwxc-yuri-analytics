"""Queue and inspect bounded user-supplied JJWXC novel cohorts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pixiv_yuri.jjwxc.persistence import (
    JjwxcDiscoveryRecord,
    JjwxcNovelRecord,
    JjwxcNovelSnapshot,
)

MAX_COHORT_NOVEL_IDS = 100
MIN_CORRELATION_SAMPLE_SIZE = 30
UPLOADED_COHORT_SOURCE = "uploaded_cohort"
UPLOADED_COHORT_PRIORITY = 120
_NOVEL_ID_PATTERN = re.compile(r"^[1-9][0-9]{0,11}$")

CohortCollectionStatus = Literal["ready", "queued", "running", "failed", "not_queued"]


@dataclass(frozen=True)
class CohortCollectionItem:
    novel_id: str
    status: CohortCollectionStatus
    error_code: str | None = None


def validate_novel_ids(novel_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Validate, deduplicate, and retain the caller's stable row order."""
    unique = tuple(dict.fromkeys(novel_ids))
    if not unique:
        raise ValueError("cohort_novel_ids_empty")
    if len(unique) > MAX_COHORT_NOVEL_IDS:
        raise ValueError("cohort_novel_ids_limit_exceeded")
    if any(_NOVEL_ID_PATTERN.fullmatch(novel_id) is None for novel_id in unique):
        raise ValueError("cohort_novel_id_invalid")
    return unique


def queue_cohort_novels(
    session: Session,
    *,
    novel_ids: tuple[str, ...],
    now: datetime | None = None,
) -> tuple[CohortCollectionItem, ...]:
    """Put missing IDs into the existing resumable discovery queue."""
    validated = validate_novel_ids(novel_ids)
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("cohort_observation_time_must_be_aware")
    ready = _ready_public_novel_ids(session, validated)
    queued = {
        item.novel_id: item
        for item in session.scalars(
            select(JjwxcDiscoveryRecord).where(JjwxcDiscoveryRecord.novel_id.in_(validated))
        ).all()
    }
    for novel_id in validated:
        if novel_id in ready:
            continue
        record = queued.get(novel_id)
        if record is None:
            record = JjwxcDiscoveryRecord(
                novel_id=novel_id,
                source_kind=UPLOADED_COHORT_SOURCE,
                priority=UPLOADED_COHORT_PRIORITY,
                status="pending",
                discovered_at=observed_at,
                next_fetch_at=observed_at,
                attempt_count=0,
            )
            session.add(record)
            queued[novel_id] = record
            continue
        if record.status != "running":
            record.status = "pending"
            record.next_fetch_at = observed_at
        record.source_kind = UPLOADED_COHORT_SOURCE
        record.priority = max(record.priority, UPLOADED_COHORT_PRIORITY)
    session.commit()
    return cohort_collection_status(session, novel_ids=validated)


def cohort_collection_status(
    session: Session,
    *,
    novel_ids: tuple[str, ...],
) -> tuple[CohortCollectionItem, ...]:
    """Return status without retrying or turning failed records into valid data."""
    validated = validate_novel_ids(novel_ids)
    ready = _ready_public_novel_ids(session, validated)
    records = {
        item.novel_id: item
        for item in session.scalars(
            select(JjwxcDiscoveryRecord).where(JjwxcDiscoveryRecord.novel_id.in_(validated))
        ).all()
    }
    items: list[CohortCollectionItem] = []
    for novel_id in validated:
        if novel_id in ready:
            items.append(CohortCollectionItem(novel_id=novel_id, status="ready"))
            continue
        record = records.get(novel_id)
        if record is None:
            items.append(CohortCollectionItem(novel_id=novel_id, status="not_queued"))
            continue
        if record.status == "failed":
            items.append(
                CohortCollectionItem(
                    novel_id=novel_id,
                    status="failed",
                    error_code=record.last_error_code or "collection_failed",
                )
            )
            continue
        status: CohortCollectionStatus = "running" if record.status == "running" else "queued"
        items.append(CohortCollectionItem(novel_id=novel_id, status=status))
    return tuple(items)


def _ready_public_novel_ids(session: Session, novel_ids: tuple[str, ...]) -> set[str]:
    return set(
        session.scalars(
            select(JjwxcNovelRecord.novel_id)
            .join(
                JjwxcNovelSnapshot,
                JjwxcNovelSnapshot.novel_record_id == JjwxcNovelRecord.id,
            )
            .where(
                JjwxcNovelRecord.novel_id.in_(novel_ids),
                JjwxcNovelSnapshot.source_mode == "public_candidate",
            )
            .distinct()
        ).all()
    )
