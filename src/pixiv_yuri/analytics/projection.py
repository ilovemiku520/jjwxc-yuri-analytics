"""Offline-only projection from validated fixtures into the normalized catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.models import EntityType
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.analytics.models import (
    CatalogAuthor,
    CatalogTag,
    CatalogWork,
    CatalogWorkMetricSnapshot,
    CatalogWorkTag,
)
from pixiv_yuri.ingest.models import RawObservation, SourceRecord


class FixtureProjectionError(ValueError):
    """Raised when a fixture cannot be tied to one validated immutable observation."""


class _AuthorRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)


class _TagRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=255)
    translated_name: str | None = Field(default=None, max_length=255)


class _Metrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    views: int | None = Field(default=None, ge=0)
    bookmarks: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)


class _WorkFixture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    published_at: datetime
    page_count: int = Field(ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    author: _AuthorRef
    tags: tuple[_TagRef, ...] = Field(max_length=100)
    metrics: _Metrics = Field(default_factory=_Metrics)

    @model_validator(mode="after")
    def unique_tags(self) -> _WorkFixture:
        names = [tag.name for tag in self.tags]
        if len(names) != len(set(names)):
            raise ValueError("fixture work contains duplicate tags")
        return self


class _AuthorFixture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)


@dataclass(frozen=True, slots=True)
class FixtureProjectionResult:
    """Deterministic projection counts; repeated runs update rather than duplicate."""

    authors: int
    works: int
    tags: int
    work_tags: int
    metric_snapshots: int


def project_fixture_catalog(
    session: Session,
    provider: FixtureProvider,
) -> FixtureProjectionResult:
    """Project only fixture payloads already persisted as exact valid observations."""
    author_keys: set[str] = set()
    work_keys: set[str] = set()
    tag_keys: set[str] = set()
    work_tag_count = 0
    metric_snapshot_count = 0

    for request in provider.list_requests():
        if request.entity_type not in {EntityType.WORK, EntityType.AUTHOR}:
            continue
        response = provider.fetch(request)
        observation = _validated_observation(
            session,
            provider.name,
            request.entity_type.value,
            request.source_id,
            response.payload_sha256,
        )
        payload = response.json_value()
        if not isinstance(payload, dict):
            raise FixtureProjectionError("fixture projection requires an object payload")

        if request.entity_type == EntityType.AUTHOR:
            author_payload = _AuthorFixture.model_validate(payload)
            _require_source_identity(request.source_id, author_payload.id)
            _upsert_author(
                session,
                provider.name,
                author_payload.id,
                author_payload.name,
                observation,
            )
            author_keys.add(author_payload.id)
            continue

        work_payload = _WorkFixture.model_validate(payload)
        _require_source_identity(request.source_id, work_payload.id)
        author = _upsert_author(
            session,
            provider.name,
            work_payload.author.id,
            work_payload.author.name,
            observation,
        )
        author_keys.add(work_payload.author.id)
        work = _upsert_work(
            session,
            provider.name,
            work_payload,
            author,
            observation,
        )
        work_keys.add(work_payload.id)
        _upsert_metric_snapshot(session, work, work_payload.metrics, observation)
        metric_snapshot_count += 1
        session.execute(delete(CatalogWorkTag).where(CatalogWorkTag.work_id == work.id))
        session.flush()
        for position, tag_payload in enumerate(work_payload.tags):
            tag = _upsert_tag(session, provider.name, tag_payload)
            tag_keys.add(tag_payload.name)
            session.add(CatalogWorkTag(work_id=work.id, tag_id=tag.id, position=position))
            work_tag_count += 1

    session.flush()
    return FixtureProjectionResult(
        authors=len(author_keys),
        works=len(work_keys),
        tags=len(tag_keys),
        work_tags=work_tag_count,
        metric_snapshots=metric_snapshot_count,
    )


def _validated_observation(
    session: Session,
    source_system: str,
    entity_type: str,
    source_id: str,
    payload_sha256: str,
) -> RawObservation:
    observation = session.scalar(
        select(RawObservation)
        .join(SourceRecord, SourceRecord.id == RawObservation.source_record_id)
        .where(
            SourceRecord.source_system == source_system,
            SourceRecord.entity_type == entity_type,
            SourceRecord.source_id == source_id,
            RawObservation.payload_sha256 == payload_sha256,
            RawObservation.validation_status == "valid",
        )
        .order_by(RawObservation.observed_at.desc(), RawObservation.id.desc())
    )
    if observation is None:
        raise FixtureProjectionError("no exact valid observation exists for fixture payload")
    return observation


def _upsert_author(
    session: Session,
    source_system: str,
    author_id: str,
    display_name: str,
    observation: RawObservation,
) -> CatalogAuthor:
    author = session.scalar(
        select(CatalogAuthor).where(
            CatalogAuthor.source_system == source_system,
            CatalogAuthor.author_id == author_id,
        )
    )
    if author is None:
        author = CatalogAuthor(
            source_system=source_system,
            author_id=author_id,
            display_name=display_name,
            latest_observation_id=observation.id,
            first_seen_at=observation.observed_at,
            last_seen_at=observation.observed_at,
        )
        session.add(author)
        session.flush()
        return author
    if _as_utc(observation.observed_at) >= _as_utc(author.last_seen_at):
        author.display_name = display_name
        author.latest_observation_id = observation.id
        author.last_seen_at = observation.observed_at
    return author


def _upsert_work(
    session: Session,
    source_system: str,
    payload: _WorkFixture,
    author: CatalogAuthor,
    observation: RawObservation,
) -> CatalogWork:
    work = session.scalar(
        select(CatalogWork).where(
            CatalogWork.source_system == source_system,
            CatalogWork.work_id == payload.id,
        )
    )
    values = {
        "title": payload.title,
        "author_id": author.id,
        "created_at": payload.published_at,
        "page_count": payload.page_count,
        "width": payload.width,
        "height": payload.height,
        "public_view_count": payload.metrics.views,
        "public_bookmark_count": payload.metrics.bookmarks,
        "public_like_count": payload.metrics.likes,
        "latest_observation_id": observation.id,
    }
    if work is None:
        work = CatalogWork(source_system=source_system, work_id=payload.id, **values)
        session.add(work)
        session.flush()
        return work
    current_observation = session.get(RawObservation, work.latest_observation_id)
    if current_observation is None:
        raise FixtureProjectionError("catalog work references a missing observation")
    if _as_utc(observation.observed_at) >= _as_utc(current_observation.observed_at):
        for field, value in values.items():
            setattr(work, field, value)
    return work


def _upsert_metric_snapshot(
    session: Session,
    work: CatalogWork,
    metrics: _Metrics,
    observation: RawObservation,
) -> CatalogWorkMetricSnapshot:
    snapshot = session.scalar(
        select(CatalogWorkMetricSnapshot).where(
            CatalogWorkMetricSnapshot.source_observation_id == observation.id
        )
    )
    if snapshot is None:
        snapshot = CatalogWorkMetricSnapshot(
            work_id=work.id,
            source_observation_id=observation.id,
            observed_at=observation.observed_at,
            public_view_count=metrics.views,
            public_bookmark_count=metrics.bookmarks,
            public_like_count=metrics.likes,
        )
        session.add(snapshot)
        session.flush()
    elif snapshot.work_id != work.id:
        raise FixtureProjectionError("metric snapshot observation is bound to another work")
    return snapshot


def _upsert_tag(session: Session, source_system: str, payload: _TagRef) -> CatalogTag:
    tag = session.scalar(
        select(CatalogTag).where(
            CatalogTag.source_system == source_system,
            CatalogTag.tag_name == payload.name,
        )
    )
    if tag is None:
        tag = CatalogTag(
            source_system=source_system,
            tag_name=payload.name,
            tag_translation=payload.translated_name,
        )
        session.add(tag)
        session.flush()
    elif payload.translated_name is not None:
        tag.tag_translation = payload.translated_name
    return tag


def _require_source_identity(expected: str, actual: str) -> None:
    if expected != actual:
        raise FixtureProjectionError("fixture source identity does not match payload identity")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
