"""Build a fail-closed Phase 6 readiness matrix without deploying anything."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DeploymentControl:
    name: str
    passed: bool
    evidence: str
    blocker: str | None


@dataclass(frozen=True, slots=True)
class DeploymentReadinessReport:
    generated_at: str
    status: str
    phase: int
    estimated_completion_percent: int
    configuration_sha256: str
    passed_control_count: int
    control_count: int
    controls: tuple[DeploymentControl, ...]
    blockers: tuple[str, ...]
    private_runtime_ready: bool
    external_publication_approved: bool
    real_source_collection_authorized: bool
    external_network_used: bool


def review_deployment_readiness(
    *,
    compose: dict[str, Any],
    api_dockerfile: str,
    web_dockerfile: str,
    phase2: dict[str, Any],
    phase3: dict[str, Any],
    phase5: dict[str, Any],
    publication: dict[str, Any],
    publication_binding: dict[str, Any] | None,
    production_evidence: dict[str, Any] | None,
    backup_restore: dict[str, Any] | None,
    runbook: str,
    now: datetime | None = None,
) -> DeploymentReadinessReport:
    services_value = compose.get("services")
    networks_value = compose.get("networks")
    services: dict[str, Any] = services_value if isinstance(services_value, dict) else {}
    networks: dict[str, Any] = networks_value if isinstance(networks_value, dict) else {}
    controls: list[DeploymentControl] = []

    def add(name: str, passed: bool, evidence: str, blocker: str) -> None:
        controls.append(
            DeploymentControl(name, passed, evidence, None if passed else blocker)
        )

    add(
        "private_phase_evidence",
        phase2.get("status") == "passed_private_only"
        and phase2.get("private_read_api_ready") is True
        and phase5.get("status") == "passed_private_fixture_only"
        and phase5.get("phase5_private_fixture_ready") is True,
        "Phase 2 private boundary and Phase 5 Fixture exit reports",
        "private_phase_evidence_invalid",
    )
    offline_network_value = networks.get("offline-db")
    offline_network = (
        offline_network_value if isinstance(offline_network_value, dict) else {}
    )
    add(
        "internal_compose_network",
        isinstance(offline_network, dict) and offline_network.get("internal") is True,
        "Compose offline-db network",
        "internal_network_not_enforced",
    )
    exposed = ("web", "api", "tls-api", "identity-api")
    add(
        "loopback_only_ports",
        all(_loopback_ports(services.get(name)) for name in exposed),
        "Published Web/API ports",
        "non_loopback_port_published",
    )
    add(
        "collection_network_disabled",
        all(
            _network_disabled(services.get(name))
            for name in ("api", "tls-api", "identity-api", "db-migrate", "fixture-ingest")
        )
        and isinstance(services.get("schema-probe"), dict)
        and services["schema-probe"].get("network_mode") == "none",
        "Runtime acquisition flags and schema-probe network mode",
        "collection_network_boundary_incomplete",
    )
    add(
        "service_healthchecks",
        all(
            isinstance(services.get(name), dict) and bool(services[name].get("healthcheck"))
            for name in ("web", "api", "postgres")
        ),
        "Web, API and PostgreSQL healthchecks",
        "required_healthcheck_missing",
    )
    add(
        "non_root_images",
        _non_root_user(api_dockerfile) and _non_root_user(web_dockerfile),
        "Final API and Web Dockerfile USER directives",
        "api_or_web_container_runs_as_root",
    )
    add(
        "immutable_app_containers",
        all(_hardened_service(services.get(name)) for name in ("web", "api")),
        "read_only, cap_drop ALL, no-new-privileges and tmpfs",
        "app_container_runtime_hardening_missing",
    )
    add(
        "non_placeholder_database_secret",
        not _contains_placeholder_secret(services),
        "Resolved Compose database credentials",
        "placeholder_database_password_configured",
    )
    add(
        "backup_restore_drill",
        _backup_restore_passed(backup_restore),
        "Isolated checksum-bound PostgreSQL restore report",
        "backup_restore_drill_missing_or_invalid",
    )
    required_runbook = (
        "## Startup",
        "## Shutdown",
        "## Backup",
        "## Restore",
        "## Incident rollback",
        "## Publication boundary",
    )
    add(
        "operator_runbook",
        all(section in runbook for section in required_runbook),
        "Versioned Phase 6 private operations runbook",
        "operator_runbook_incomplete",
    )
    add(
        "production_identity_and_tls",
        bool(
            production_evidence
            and production_evidence.get("status") == "reviewed"
            and production_evidence.get("identity_reviewed") is True
            and production_evidence.get("tls_reviewed") is True
            and production_evidence.get("production_deployment_reviewed") is True
            and production_evidence.get("violations") == []
            and production_evidence.get("external_network_used") is False
            and production_evidence.get("external_publication_approved") is False
            and production_evidence.get("real_source_collection_authorized") is False
        ),
        "Versioned non-secret production identity/TLS evidence review",
        "production_identity_or_tls_not_reviewed",
    )
    add(
        "external_publication_approval",
        publication.get("status") == "approved"
        and publication.get("external_publication_approved") is True
        and not publication.get("violations")
        and bool(
            publication_binding
            and publication_binding.get("status") == "bound"
            and publication_binding.get("violations") == []
            and publication_binding.get("external_publication_approved") is False
            and publication_binding.get("real_source_collection_authorized") is False
            and publication_binding.get("external_network_used") is False
        ),
        "Accountable publication review and production-evidence binding",
        "external_publication_not_approved",
    )

    blockers = tuple(control.blocker for control in controls if control.blocker is not None)
    ready = not blockers
    fingerprint_input = {
        "compose": compose,
        "api_dockerfile": api_dockerfile,
        "web_dockerfile": web_dockerfile,
        "runbook": runbook,
    }
    configuration_sha256 = hashlib.sha256(
        json.dumps(
            fingerprint_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("deployment review time must include a timezone")
    return DeploymentReadinessReport(
        generated_at=checked_at.astimezone(UTC).isoformat(),
        status=(
            "ready_for_accountable_private_deployment"
            if ready
            else "offline_preparation_blocked"
        ),
        phase=6,
        estimated_completion_percent=(100 if ready else 60),
        configuration_sha256=configuration_sha256,
        passed_control_count=sum(control.passed for control in controls),
        control_count=len(controls),
        controls=tuple(controls),
        blockers=blockers,
        private_runtime_ready=ready,
        external_publication_approved=False,
        real_source_collection_authorized=False,
        external_network_used=False,
    )


def _loopback_ports(service: object) -> bool:
    if not isinstance(service, dict):
        return False
    ports = service.get("ports")
    if ports is None:
        return True
    if not isinstance(ports, list):
        return False
    return all(
        isinstance(port, dict)
        and port.get("host_ip") in {"127.0.0.1", "::1"}
        for port in ports
    )


def _network_disabled(service: object) -> bool:
    if not isinstance(service, dict) or not isinstance(service.get("environment"), dict):
        return False
    return str(service["environment"].get("PYURI_ENABLE_NETWORK", "")).lower() == "false"


def _non_root_user(dockerfile: str) -> bool:
    matches = re.findall(r"(?im)^USER\s+([^\s#]+)", dockerfile)
    return bool(matches) and matches[-1].lower() not in {"0", "root"}


def _hardened_service(service: object) -> bool:
    if not isinstance(service, dict):
        return False
    cap_drop = service.get("cap_drop")
    security_opt = service.get("security_opt")
    return (
        service.get("read_only") is True
        and isinstance(cap_drop, list)
        and "ALL" in cap_drop
        and isinstance(security_opt, list)
        and any(str(value).lower() == "no-new-privileges:true" for value in security_opt)
        and bool(service.get("tmpfs"))
    )


def _contains_placeholder_secret(services: dict[str, Any]) -> bool:
    rendered = json.dumps(services, ensure_ascii=False).lower()
    return "change-me" in rendered or "placeholder" in rendered


def _backup_restore_passed(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    source_counts = report.get("source_table_counts")
    restored_counts = report.get("restored_table_counts")
    if not isinstance(source_counts, dict) or not isinstance(restored_counts, dict):
        return False
    required_tables = {
        "crawl_runs",
        "raw_observations",
        "schema_definitions",
        "quarantine_records",
        "catalog_authors",
        "catalog_works",
        "catalog_tags",
        "catalog_work_tags",
        "catalog_work_metric_snapshots",
    }
    if set(source_counts) != required_tables or source_counts != restored_counts:
        return False
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in source_counts.values()
    ):
        return False
    verified_total = sum(source_counts.values())
    return bool(
        report.get("status") == "passed_offline_restore_drill"
        and report.get("isolated_restore") is True
        and report.get("backup_sha256_verified") is True
        and isinstance(report.get("backup_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", report["backup_sha256"])
        and isinstance(report.get("backup_size_bytes"), int)
        and not isinstance(report.get("backup_size_bytes"), bool)
        and report["backup_size_bytes"] > 0
        and report.get("schema_version_verified") is True
        and isinstance(report.get("schema_version"), str)
        and re.fullmatch(r"[0-9_]+", report["schema_version"])
        and report.get("table_counts_match") is True
        and verified_total > 0
        and isinstance(report.get("source_row_count"), int)
        and not isinstance(report.get("source_row_count"), bool)
        and isinstance(report.get("restored_row_count"), int)
        and not isinstance(report.get("restored_row_count"), bool)
        and report.get("source_row_count") == verified_total
        and report.get("restored_row_count") == verified_total
        and report.get("runtime_secret_generated") is True
        and report.get("secret_persisted") is False
        and report.get("canonical_volume_untouched") is True
        and report.get("external_network_used") is False
    )


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"input must be an object: {path.name}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-json", type=Path, required=True)
    parser.add_argument("--api-dockerfile", type=Path, default=Path("apps/api/Dockerfile"))
    parser.add_argument("--web-dockerfile", type=Path, default=Path("apps/web/Dockerfile"))
    parser.add_argument("--phase2", type=Path, default=Path("var/reports/phase2_exit_review.json"))
    parser.add_argument(
        "--phase3", type=Path, default=Path("var/reports/phase3_security_review.json")
    )
    parser.add_argument("--phase5", type=Path, default=Path("var/reports/phase5_exit_review.json"))
    parser.add_argument(
        "--publication", type=Path, default=Path("var/reports/publication_review.json")
    )
    parser.add_argument(
        "--production-evidence",
        type=Path,
        default=Path("var/reports/production_identity_tls_review.json"),
    )
    parser.add_argument(
        "--publication-binding",
        type=Path,
        default=Path("var/reports/production_publication_binding.json"),
    )
    parser.add_argument("--backup-restore", type=Path)
    parser.add_argument("--runbook", type=Path, default=Path("docs/phase6-private-runbook.md"))
    parser.add_argument("--output", type=Path, default=Path("var/reports/phase6_readiness.json"))
    args = parser.parse_args(argv)
    backup = _load_object(args.backup_restore) if args.backup_restore else None
    report = review_deployment_readiness(
        compose=_load_object(args.compose_json),
        api_dockerfile=args.api_dockerfile.read_text(encoding="utf-8"),
        web_dockerfile=args.web_dockerfile.read_text(encoding="utf-8"),
        phase2=_load_object(args.phase2),
        phase3=_load_object(args.phase3),
        phase5=_load_object(args.phase5),
        publication=_load_object(args.publication),
        publication_binding=_load_object(args.publication_binding),
        production_evidence=_load_object(args.production_evidence),
        backup_restore=backup,
        runbook=args.runbook.read_text(encoding="utf-8"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
