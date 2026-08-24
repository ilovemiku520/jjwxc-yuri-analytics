"""Durable task queue for author-authorized VIP click imports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from pixiv_yuri.ingest.models import CrawlRun, CrawlTask
from pixiv_yuri.jjwxc.author_v_import import AuthorVClickRecord, import_author_v_clicks

JOB_RUN_TYPE = "jjwxc_author_v_click_import"
JOB_TASK_TYPE = "jjwxc_author_v_click_batch"


@dataclass(frozen=True, slots=True)
class AuthorVJobStatus:
    job_id: int
    status: Literal["pending", "running", "completed", "failed"]
    task_status: Literal["pending", "running", "succeeded", "failed"]
    attempt_count: int
    record_count: int
    last_error_code: str | None
    novel_ids: tuple[str, ...]


def enqueue_author_v_job(session: Session, *, payload: dict[str, Any]) -> AuthorVJobStatus:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("author_v_job_records_invalid")
    now = datetime.now(UTC)
    run = CrawlRun(
        run_type=JOB_RUN_TYPE,
        provider="author_browser_export",
        status="pending",
        config_snapshot={"record_count": len(records), "payload_sha256": digest},
        requested_by="internal_author_import",
    )
    session.add(run)
    session.flush()
    task = CrawlTask(
        run_id=run.id,
        task_type=JOB_TASK_TYPE,
        logical_target=canonical,
        idempotency_key=digest,
        priority=100,
        status="pending",
        available_at=now,
    )
    session.add(task)
    session.commit()
    return AuthorVJobStatus(
        run.id,
        "pending",
        "pending",
        0,
        len(records),
        None,
        _novel_ids(canonical),
    )


def author_v_job_status(session: Session, *, job_id: int) -> AuthorVJobStatus:
    run = session.get(CrawlRun, job_id)
    if run is None or run.run_type != JOB_RUN_TYPE:
        raise ValueError("author_v_job_not_found")
    task = session.scalar(select(CrawlTask).where(CrawlTask.run_id == run.id))
    if task is None:
        raise ValueError("author_v_job_task_missing")
    return _status(run, task)


def retry_author_v_job(session: Session, *, job_id: int) -> AuthorVJobStatus:
    run = session.get(CrawlRun, job_id)
    if run is None or run.run_type != JOB_RUN_TYPE:
        raise ValueError("author_v_job_not_found")
    task = session.scalar(select(CrawlTask).where(CrawlTask.run_id == run.id))
    if task is None or task.status != "failed":
        raise ValueError("author_v_job_not_retryable")
    if task.attempt_count >= 3:
        raise ValueError("author_v_job_retry_limit_reached")
    task.status = "pending"
    task.available_at = datetime.now(UTC)
    task.lease_until = None
    task.last_error_code = None
    run.status = "pending"
    run.finished_at = None
    run.stop_reason = None
    session.commit()
    return _status(run, task)


def process_next_author_v_job(session: Session, *, worker_id: str) -> bool:
    del worker_id  # Worker identity is intentionally not retained in minimized task state.
    now = datetime.now(UTC)
    stale = list(
        session.scalars(
            select(CrawlTask).where(
                CrawlTask.task_type == JOB_TASK_TYPE,
                CrawlTask.status == "running",
                CrawlTask.lease_until < now,
            )
        ).all()
    )
    for stale_task in stale:
        stale_task.status = "pending"
        stale_task.available_at = now
        stale_task.lease_until = None
        stale_task.last_error_code = "worker_lease_expired"
    session.commit()
    task = session.scalar(
        select(CrawlTask)
        .where(
            CrawlTask.task_type == JOB_TASK_TYPE,
            CrawlTask.status == "pending",
            CrawlTask.available_at <= now,
        )
        .order_by(CrawlTask.priority.desc(), CrawlTask.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if task is None:
        session.rollback()
        return False
    run = session.get(CrawlRun, task.run_id)
    if run is None:
        task.status = "failed"
        task.last_error_code = "job_run_missing"
        session.commit()
        return True
    task.status = "running"
    task.attempt_count += 1
    task.lease_until = now + timedelta(minutes=10)
    run.status = "running"
    run.started_at = run.started_at or now
    session.commit()
    try:
        payload = json.loads(task.logical_target)
        records = tuple(
            AuthorVClickRecord(
                novel_id=str(item["novel_id"]),
                chapter_id=int(item["chapter_id"]),
                click_count=int(item["click_count"]),
            )
            for item in payload["records"]
        )
        observed_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        results = import_author_v_clicks(
            session,
            records=records,
            observed_at=observed_at,
            authorization_attested=payload["authorization_attestation"] is True,
        )
        rejected = [item for item in results if item.status == "rejected"]
        if rejected:
            raise ValueError(rejected[0].error_code or "author_v_import_rejected")
        task.status = "succeeded"
        task.lease_until = None
        task.last_error_code = None
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        session.commit()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        session.rollback()
        failed_task = session.get(CrawlTask, task.id)
        failed_run = session.get(CrawlRun, run.id)
        if failed_task is not None:
            failed_task.status = "failed"
            failed_task.lease_until = None
            failed_task.last_error_code = _error_code(exc)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.finished_at = datetime.now(UTC)
            failed_run.stop_reason = _error_code(exc)
        session.commit()
    return True


def _status(run: CrawlRun, task: CrawlTask) -> AuthorVJobStatus:
    config = run.config_snapshot
    run_status = "completed" if run.status == "completed" else cast(
        Literal["pending", "running", "failed"], run.status
    )
    return AuthorVJobStatus(
        run.id,
        run_status,
        cast(Literal["pending", "running", "succeeded", "failed"], task.status),
        task.attempt_count,
        int(config.get("record_count", 0)),
        task.last_error_code,
        _novel_ids(task.logical_target),
    )


def _novel_ids(logical_target: str) -> tuple[str, ...]:
    """Expose only stable work IDs for reports; never return clicks or chapter payloads."""
    try:
        payload = json.loads(logical_target)
        records = payload.get("records", [])
        identifiers = {
            str(item.get("novel_id", ""))
            for item in records
            if isinstance(item, dict)
            and str(item.get("novel_id", "")).isdigit()
            and str(item.get("novel_id", "")) != "0"
        }
    except (AttributeError, TypeError, json.JSONDecodeError):
        return ()
    return tuple(sorted(identifiers, key=int)[:20])


def _error_code(exc: Exception) -> str:
    value = str(exc)
    safe = value and len(value) <= 100 and value.replace("_", "").isalnum()
    return value if safe else "job_failed"
