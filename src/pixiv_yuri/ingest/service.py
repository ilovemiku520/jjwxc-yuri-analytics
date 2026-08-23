"""Persist an offline FixtureProvider run into the durable ingest ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.models import AcquisitionRequest, RawResponse
from pixiv_yuri.acquisition.parsers.registry import ParserRegistry
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider, FixtureProviderError
from pixiv_yuri.data_quality.models import SchemaPolicy, ValidationItem, ValidationState
from pixiv_yuri.data_quality.validation import ensure_policy_provider, validate_response
from pixiv_yuri.ingest.models import (
    CrawlRun,
    CrawlTask,
    QuarantineRecord,
    RawObservation,
    SchemaDefinition,
    SourceRecord,
    TaskAttempt,
)
from pixiv_yuri.schema_probe.analyzer import describe_payload, fingerprint_payload
from pixiv_yuri.shared.database import utc_now


@dataclass(frozen=True, slots=True)
class FixtureIngestResult:
    """Auditable counts returned after one committed fixture run."""

    run_id: int
    task_count: int
    succeeded_tasks: int
    failed_tasks: int
    created_observations: int
    duplicate_observations: int
    created_schema_definitions: int
    quarantine_records: int


def ingest_fixture_provider(
    session: Session,
    provider: FixtureProvider,
    *,
    requested_by: str = "offline-cli",
    schema_policy: SchemaPolicy | None = None,
    parser_registry: ParserRegistry | None = None,
) -> FixtureIngestResult:
    """Run a deterministic, transactional fixture ingestion.

    The function never stores payload bytes. It stores only a fixture object key,
    content hash, schema descriptor and operational metadata.
    """
    if (schema_policy is None) != (parser_registry is None):
        raise ValueError("schema_policy and parser_registry must be provided together.")
    if schema_policy is not None:
        ensure_policy_provider(schema_policy, provider.name)

    started_at = utc_now()
    run = CrawlRun(
        run_type="offline_fixture_ingest",
        provider=provider.name,
        status="running",
        config_snapshot={"offline": True, "provider": provider.name},
        budget_limit=Decimal("0"),
        budget_used=Decimal("0"),
        requested_by=requested_by,
        started_at=started_at,
    )
    session.add(run)
    session.flush()

    succeeded = 0
    failed = 0
    created_observations = 0
    duplicate_observations = 0
    created_schemas = 0
    quarantine_count = 0
    validation_quarantines = 0
    requests = provider.list_requests()

    for request in requests:
        source_record = _get_or_create_source_record(session, provider.name, request, started_at)
        task = CrawlTask(
            run_id=run.id,
            source_record_id=source_record.id,
            task_type="fixture_fetch",
            logical_target=f"{request.entity_type.value}/{request.source_id}",
            idempotency_key=f"fixture:{request.entity_type.value}:{request.source_id}",
            status="running",
            attempt_count=1,
            available_at=started_at,
        )
        session.add(task)
        session.flush()

        attempt = TaskAttempt(
            task_id=task.id,
            attempt_no=1,
            worker_id="offline-fixture-worker",
            status="running",
            trace_id=uuid4().hex,
            started_at=utc_now(),
        )
        session.add(attempt)
        session.flush()

        try:
            response = provider.fetch(request)
            attempt.http_status = response.status_code
            attempt.bytes_received = len(response.body)
            _update_source_availability(source_record, response)
            if not 200 <= response.status_code < 300:
                raise FixtureProviderError(f"Non-success fixture status: {response.status_code}")

            validation = (
                validate_response(response, schema_policy, parser_registry)
                if schema_policy is not None and parser_registry is not None
                else None
            )
            observation, was_created, schema_created = _persist_response(
                session, source_record, attempt, response, validation
            )
            created_observations += int(was_created)
            duplicate_observations += int(not was_created)
            created_schemas += int(schema_created)
            if validation is not None and validation.state == ValidationState.QUARANTINED:
                validation_quarantines += 1
                quarantine_count += int(
                    _persist_validation_quarantine(
                        session,
                        observation,
                        attempt,
                        validation,
                    )
                )
            task.status = "succeeded"
            attempt.status = "succeeded"
            attempt.finished_at = utc_now()
            succeeded += 1
        except (FixtureProviderError, OSError, UnicodeError, ValueError) as exc:
            detail = str(exc)[:2000]
            task.status = "failed"
            task.last_error_code = "fixture_ingest_error"
            attempt.status = "failed"
            attempt.error_code = "fixture_ingest_error"
            attempt.finished_at = utc_now()
            session.add(
                QuarantineRecord(
                    task_attempt_id=attempt.id,
                    entity_type=request.entity_type.value,
                    source_id=request.source_id,
                    error_code="fixture_ingest_error",
                    detail=detail,
                    status="open",
                )
            )
            failed += 1
            quarantine_count += 1

    run.status = (
        "completed"
        if failed == 0 and validation_quarantines == 0
        else "completed_with_errors"
    )
    run.finished_at = utc_now()
    session.flush()
    if run.id is None:
        raise RuntimeError("Crawl run did not receive a database identifier.")

    return FixtureIngestResult(
        run_id=run.id,
        task_count=len(requests),
        succeeded_tasks=succeeded,
        failed_tasks=failed,
        created_observations=created_observations,
        duplicate_observations=duplicate_observations,
        created_schema_definitions=created_schemas,
        quarantine_records=quarantine_count,
    )


def _get_or_create_source_record(
    session: Session,
    source_system: str,
    request: AcquisitionRequest,
    seen_at: datetime,
) -> SourceRecord:
    record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source_system == source_system,
            SourceRecord.entity_type == request.entity_type.value,
            SourceRecord.source_id == request.source_id,
        )
    )
    if record is None:
        record = SourceRecord(
            source_system=source_system,
            entity_type=request.entity_type.value,
            source_id=request.source_id,
            current_availability="unknown",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        session.add(record)
        session.flush()
    return record


def _persist_response(
    session: Session,
    source_record: SourceRecord,
    attempt: TaskAttempt,
    response: RawResponse,
    validation: ValidationItem | None,
) -> tuple[RawObservation, bool, bool]:
    payload = response.json_value()
    fingerprint = fingerprint_payload(payload)
    schema_definition = session.scalar(
        select(SchemaDefinition).where(
            SchemaDefinition.entity_type == response.entity_type.value,
            SchemaDefinition.fingerprint == fingerprint,
        )
    )
    schema_created = schema_definition is None
    if schema_definition is None:
        schema_definition = SchemaDefinition(
            entity_type=response.entity_type.value,
            fingerprint=fingerprint,
            definition=describe_payload(payload),
            sample_count=0,
            status="discovered",
            first_seen_at=response.observed_at,
            last_seen_at=response.observed_at,
        )
        session.add(schema_definition)
        # The session disables autoflush; persist now so later records in this
        # batch can reuse the same fingerprint without violating uniqueness.
        session.flush()

    existing = session.scalar(
        select(RawObservation).where(
            RawObservation.source_record_id == source_record.id,
            RawObservation.payload_sha256 == response.payload_sha256,
            RawObservation.observed_at == response.observed_at,
        )
    )
    if existing is not None:
        if validation is not None and existing.validation_status == "pending":
            existing.validation_status = validation.state.value
            existing.parser_version = validation.parser_version
        schema_definition.last_seen_at = max(
            _as_utc(schema_definition.last_seen_at), _as_utc(response.observed_at)
        )
        return existing, False, schema_created

    object_key = str(
        response.metadata.get(
            "fixture_path",
            f"fixture/{response.entity_type.value}/{response.source_id}/{response.payload_sha256}.json",
        )
    )
    safe_metadata = {
        key: value
        for key, value in response.metadata.items()
        if key in {"fixture_path", "fixture_version", "synthetic"}
    }
    observation = RawObservation(
        source_record_id=source_record.id,
        task_attempt_id=attempt.id,
        observed_at=response.observed_at,
        status_code=response.status_code,
        content_type=response.content_type,
        payload_sha256=response.payload_sha256,
        payload_object_key=object_key,
        payload_bytes=len(response.body),
        schema_fingerprint=fingerprint,
        parser_version=validation.parser_version if validation is not None else None,
        validation_status=validation.state.value if validation is not None else "pending",
        observation_metadata=safe_metadata,
    )
    session.add(observation)
    session.flush()
    schema_definition.sample_count += 1
    schema_definition.last_seen_at = max(
        _as_utc(schema_definition.last_seen_at), _as_utc(response.observed_at)
    )
    return observation, True, schema_created


def _persist_validation_quarantine(
    session: Session,
    observation: RawObservation,
    attempt: TaskAttempt,
    validation: ValidationItem,
) -> bool:
    existing = session.scalar(
        select(QuarantineRecord.id).where(
            QuarantineRecord.raw_observation_id == observation.id,
            QuarantineRecord.error_code == validation.code,
            QuarantineRecord.status == "open",
        )
    )
    if existing is not None:
        return False
    session.add(
        QuarantineRecord(
            raw_observation_id=observation.id,
            task_attempt_id=attempt.id,
            entity_type=validation.entity_type.value,
            source_id=validation.source_id,
            error_code=validation.code,
            detail=validation.detail[:2000],
            status="open",
        )
    )
    return True


def _update_source_availability(source_record: SourceRecord, response: RawResponse) -> None:
    source_record.source_url = response.source_url
    source_record.last_seen_at = response.observed_at
    if 200 <= response.status_code < 300:
        source_record.current_availability = "available"
    elif response.status_code in {401, 403}:
        source_record.current_availability = "restricted"
    elif response.status_code in {404, 410}:
        source_record.current_availability = "missing"
    else:
        source_record.current_availability = "unknown"


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps read from SQLite or PostgreSQL before comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
