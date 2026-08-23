"""Bounded PixivPy3 App-API metadata adapter for private research."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from getpass import getpass
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pixiv_yuri.acquisition.browser_export_import import (
    PublicTag,
    SanitizedPublicMetadata,
)
from pixiv_yuri.acquisition.operator_session import OperatorSessionFactory, RuntimeSession
from pixiv_yuri.acquisition.providers.pixiv_oauth_pkce import (
    PixivOAuthPkceError,
    open_runtime_oauth_session,
)
from pixiv_yuri.governance.g0 import G0Approval, load_active_g0_approval


class PixivAppApiOperation(StrEnum):
    """Read-only App API operations approved for efficient metadata discovery."""

    SEARCH_ILLUST = "search_illust"
    USER_ILLUSTS = "user_illusts"
    ILLUST_RANKING = "illust_ranking"


class PixivAppApiPolicy(BaseModel):
    """Fail-closed local boundary for the unofficial library integration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1, le=1)
    provider: str = Field(pattern=r"^pixivpy3_app_api$")
    library_version: str = Field(pattern=r"^3\.7\.5$")
    allowed_operations: set[PixivAppApiOperation] = Field(min_length=1)
    authentication_modes: set[Literal["oauth_pkce", "runtime_refresh_token"]] = Field(
        min_length=1
    )
    requests_per_minute: int = Field(ge=1, le=30)
    network_concurrency: int = Field(ge=1, le=1)
    max_pages_per_run: int = Field(ge=1, le=100)
    max_records_per_page: int = Field(ge=1, le=30)
    max_candidate_records_per_run: int = Field(ge=1, le=3_000)
    local_processing_workers: int = Field(ge=1, le=8)
    password_input_allowed: bool
    secret_persistence_allowed: bool
    raw_payload_persistence_allowed: bool
    media_download_allowed: bool
    automatic_retry_allowed: bool
    canonical_ingest_authorized: bool

    def require_fixed_safety_boundary(self) -> None:
        """Reject a policy that weakens credential, payload, media, or retry controls."""
        if any(
            (
                self.password_input_allowed,
                self.secret_persistence_allowed,
                self.raw_payload_persistence_allowed,
                self.media_download_allowed,
                self.automatic_retry_allowed,
                self.canonical_ingest_authorized,
            )
        ):
            raise ValueError("Pixiv App API policy weakens the fixed safety boundary.")
        if self.max_candidate_records_per_run > (
            self.max_pages_per_run * self.max_records_per_page
        ):
            raise ValueError("Candidate cap exceeds the bounded page capacity.")


class PixivAppApiClient(Protocol):
    """Narrow interface implemented by the reviewed PixivPy3 wrapper."""

    def fetch_page(
        self,
        operation: PixivAppApiOperation,
        parameters: Mapping[str, object],
    ) -> Mapping[str, Any]: ...

    def next_parameters(
        self,
        operation: PixivAppApiOperation,
        payload: Mapping[str, Any],
    ) -> Mapping[str, object] | None: ...


class PixivAppApiError(RuntimeError):
    """Payload-free failure from authentication, transport, or schema handling."""


@dataclass(frozen=True, slots=True)
class PixivAppApiCollectionReport:
    """Value-free performance and safety evidence for one in-memory run."""

    status: str
    generated_at: str
    operation: str
    authentication_mode: str
    requested_pages: int
    input_records: int
    candidate_records: int
    duplicate_records: int
    skipped_records: int
    external_network_used: bool
    oauth_authorization_code_requested: bool
    refresh_token_requested: bool
    password_requested: bool
    secret_persisted: bool
    raw_payload_persisted: bool
    media_persisted: bool
    automatic_retries: int
    network_concurrency: int
    canonical_ingest_authorized: bool
    violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PixivAppApiCollection:
    records: tuple[SanitizedPublicMetadata, ...]
    report: PixivAppApiCollectionReport


class PixivAppApiCollector:
    """Fetch bounded pages serially and minimize every page before continuing."""

    def __init__(
        self,
        client: PixivAppApiClient,
        policy: PixivAppApiPolicy,
        approval: G0Approval,
        *,
        authentication_mode: Literal["oauth_pkce", "runtime_refresh_token"] = (
            "runtime_refresh_token"
        ),
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        validate_pixiv_app_api_boundary(policy, approval)
        self._client = client
        self._policy = policy
        if authentication_mode not in policy.authentication_modes:
            raise ValueError("App API authentication mode is outside the reviewed policy.")
        self._authentication_mode = authentication_mode
        self._sleep = sleeper
        self._monotonic = monotonic

    def collect(
        self,
        operation: PixivAppApiOperation,
        parameters: Mapping[str, object],
        *,
        max_pages: int | None = None,
    ) -> PixivAppApiCollection:
        """Collect one search/author/ranking sequence without retries or raw storage."""
        if operation not in self._policy.allowed_operations:
            raise ValueError("App API operation is outside the reviewed policy.")
        page_limit = max_pages or self._policy.max_pages_per_run
        if not 1 <= page_limit <= self._policy.max_pages_per_run:
            raise ValueError("Requested page limit is outside the reviewed policy.")
        current: dict[str, object] | None = _validate_parameters(operation, parameters)
        records: list[SanitizedPublicMetadata] = []
        seen: set[str] = set()
        requested_pages = 0
        input_records = 0
        duplicates = 0
        skipped = 0
        previous_request_at: float | None = None

        while current is not None and requested_pages < page_limit:
            if previous_request_at is not None:
                interval = 60.0 / self._policy.requests_per_minute
                self._sleep(max(0.0, interval - (self._monotonic() - previous_request_at)))
            previous_request_at = self._monotonic()
            try:
                payload = self._client.fetch_page(operation, current)
            except Exception:
                raise PixivAppApiError("pixiv_app_api_request_failed") from None
            requested_pages += 1
            try:
                page_records, page_skipped, page_input = sanitize_pixiv_app_api_page(
                    payload,
                    local_workers=self._policy.local_processing_workers,
                )
            except (PixivAppApiError, ValidationError, ValueError):
                raise PixivAppApiError("pixiv_app_api_schema_invalid") from None
            input_records += page_input
            skipped += page_skipped
            for record in page_records:
                if record.work_id in seen:
                    duplicates += 1
                    continue
                if len(records) >= self._policy.max_candidate_records_per_run:
                    current = None
                    break
                seen.add(record.work_id)
                records.append(record)
            else:
                next_values = self._client.next_parameters(operation, payload)
                current = (
                    _validate_parameters(operation, next_values)
                    if next_values is not None
                    else None
                )

        return PixivAppApiCollection(
            records=tuple(records),
            report=PixivAppApiCollectionReport(
                status="candidate_ready" if records else "blocked",
                generated_at=datetime.now(UTC).isoformat(),
                operation=operation.value,
                authentication_mode=self._authentication_mode,
                requested_pages=requested_pages,
                input_records=input_records,
                candidate_records=len(records),
                duplicate_records=duplicates,
                skipped_records=skipped,
                external_network_used=requested_pages > 0,
                oauth_authorization_code_requested=(
                    self._authentication_mode == "oauth_pkce"
                ),
                refresh_token_requested=(
                    self._authentication_mode == "runtime_refresh_token"
                ),
                password_requested=False,
                secret_persisted=False,
                raw_payload_persisted=False,
                media_persisted=False,
                automatic_retries=0,
                network_concurrency=1,
                canonical_ingest_authorized=False,
                violations=("pixiv_app_api_no_candidates",) if not records else (),
            ),
        )


class PixivPy3Client:
    """Runtime-only authenticated wrapper around the pinned PixivPy3 release."""

    def __init__(self, api: Any) -> None:
        self._api = api

    @classmethod
    def authenticate(
        cls,
        session: RuntimeSession,
        *,
        proxy: str | None = None,
    ) -> PixivPy3Client:
        """Consume one hidden refresh-token lease and retain only the access token."""
        try:
            if package_version("pixivpy3") != "3.7.5":
                raise PixivAppApiError("pixivpy3_version_mismatch")
            from pixivpy3 import AppPixivAPI

            options = {"proxies": {"https": proxy}} if proxy else {}
            api = AppPixivAPI(**options)
            refresh_token = session.reveal_for_request()
            try:
                api.auth(refresh_token=refresh_token)
            finally:
                refresh_token = ""
                session.close()
            api.refresh_token = None
            return cls(api)
        except PixivAppApiError:
            raise
        except Exception:
            session.close()
            raise PixivAppApiError("pixiv_app_api_auth_failed") from None

    @classmethod
    def authenticate_access_token(
        cls,
        session: RuntimeSession,
        *,
        proxy: str | None = None,
    ) -> PixivPy3Client:
        """Consume one PKCE access-token lease without retaining refresh credentials."""
        try:
            if package_version("pixivpy3") != "3.7.5":
                raise PixivAppApiError("pixivpy3_version_mismatch")
            from pixivpy3 import AppPixivAPI

            options = {"proxies": {"https": proxy}} if proxy else {}
            api = AppPixivAPI(**options)
            access_token = session.reveal_for_request()
            try:
                api.set_auth(access_token, None)
            finally:
                access_token = ""
                session.close()
            return cls(api)
        except PixivAppApiError:
            raise
        except Exception:
            session.close()
            raise PixivAppApiError("pixiv_app_api_auth_failed") from None

    def fetch_page(
        self,
        operation: PixivAppApiOperation,
        parameters: Mapping[str, object],
    ) -> Mapping[str, Any]:
        values = dict(parameters)
        if operation == PixivAppApiOperation.SEARCH_ILLUST:
            payload = self._api.search_illust(**values)
        elif operation == PixivAppApiOperation.USER_ILLUSTS:
            payload = self._api.user_illusts(**values)
        elif operation == PixivAppApiOperation.ILLUST_RANKING:
            payload = self._api.illust_ranking(**values)
        else:
            raise PixivAppApiError("pixiv_app_api_operation_not_supported")
        if not isinstance(payload, Mapping):
            raise PixivAppApiError("pixiv_app_api_response_invalid")
        return cast(Mapping[str, Any], payload)

    def next_parameters(
        self,
        operation: PixivAppApiOperation,
        payload: Mapping[str, Any],
    ) -> Mapping[str, object] | None:
        del operation
        next_url = payload.get("next_url")
        if next_url in (None, ""):
            return None
        if not isinstance(next_url, str):
            raise PixivAppApiError("pixiv_app_api_next_page_invalid")
        values = self._api.parse_qs(next_url)
        if values is None:
            return None
        if not isinstance(values, Mapping):
            raise PixivAppApiError("pixiv_app_api_next_page_invalid")
        return cast(Mapping[str, object], values)


def load_pixiv_app_api_policy(path: Path) -> PixivAppApiPolicy:
    policy = PixivAppApiPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    policy.require_fixed_safety_boundary()
    return policy


def validate_pixiv_app_api_boundary(
    policy: PixivAppApiPolicy, approval: G0Approval
) -> None:
    policy.require_fixed_safety_boundary()
    if "pixiv_app_api" not in approval.source_scope.access_methods:
        raise ValueError("Active G0 does not approve the Pixiv App API method.")
    if policy.requests_per_minute > approval.traffic_limits.requests_per_minute:
        raise ValueError("App API policy exceeds the G0 request rate.")
    if policy.max_pages_per_run > approval.traffic_limits.per_run_request_cap:
        raise ValueError("App API policy exceeds the G0 per-run request cap.")
    if policy.network_concurrency > approval.traffic_limits.concurrency:
        raise ValueError("App API policy exceeds the G0 concurrency limit.")


def sanitize_pixiv_app_api_page(
    payload: Mapping[str, Any],
    *,
    local_workers: int = 1,
) -> tuple[tuple[SanitizedPublicMetadata, ...], int, int]:
    """Minimize one App API page and discard media URLs, captions, and raw payload."""
    source_records = payload.get("illusts")
    if not isinstance(source_records, list) or len(source_records) > 30:
        raise PixivAppApiError("pixiv_app_api_page_schema_invalid")
    if not 1 <= local_workers <= 8:
        raise ValueError("Local App API workers must be between 1 and 8.")
    with ThreadPoolExecutor(
        max_workers=local_workers,
        thread_name_prefix="pyuri-app-api-local",
    ) as executor:
        minimized = tuple(executor.map(_sanitize_pixiv_app_api_record, source_records))
    return (
        tuple(record for record in minimized if record is not None),
        sum(record is None for record in minimized),
        len(source_records),
    )


def _sanitize_pixiv_app_api_record(value: object) -> SanitizedPublicMetadata | None:
    if not isinstance(value, Mapping):
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    if value.get("visible") is False:
        return None
    rating = value.get("x_restrict")
    if type(rating) is not int or rating not in {0, 1, 2}:
        raise PixivAppApiError("pixiv_app_api_rating_invalid")
    user = value.get("user")
    tags = value.get("tags")
    if not isinstance(user, Mapping) or not isinstance(tags, list):
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    public_tags: list[PublicTag] = []
    for tag in tags[:10]:
        if not isinstance(tag, Mapping):
            raise PixivAppApiError("pixiv_app_api_tag_schema_invalid")
        translated = tag.get("translated_name")
        if translated is not None and not isinstance(translated, str):
            raise PixivAppApiError("pixiv_app_api_tag_schema_invalid")
        try:
            public_tags.append(
                PublicTag(
                    tag_name=_required_string(tag.get("name")),
                    tag_translation=translated,
                )
            )
        except (PixivAppApiError, ValidationError):
            raise PixivAppApiError("pixiv_app_api_tag_schema_invalid") from None
    try:
        return SanitizedPublicMetadata(
            work_id=str(_required_integer(value.get("id"))),
            work_title=_required_string(value.get("title")),
            author_id=str(_required_integer(user.get("id"))),
            author_display_name=_required_string(user.get("name")),
            public_tags=public_tags,
            created_at=_required_datetime(value.get("create_date")),
            page_count=_required_integer(value.get("page_count")),
            width=_required_integer(value.get("width")),
            height=_required_integer(value.get("height")),
            public_view_count=_optional_integer(value.get("total_view")),
            public_bookmark_count=_optional_integer(value.get("total_bookmarks")),
            public_like_count=None,
        )
    except (PixivAppApiError, ValidationError):
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid") from None


_PARAMETER_KEYS: dict[PixivAppApiOperation, frozenset[str]] = {
    PixivAppApiOperation.SEARCH_ILLUST: frozenset(
        {
            "word",
            "search_target",
            "sort",
            "duration",
            "start_date",
            "end_date",
            "filter",
            "offset",
        }
    ),
    PixivAppApiOperation.USER_ILLUSTS: frozenset({"user_id", "type", "filter", "offset"}),
    PixivAppApiOperation.ILLUST_RANKING: frozenset({"mode", "date", "filter", "offset"}),
}


def _validate_parameters(
    operation: PixivAppApiOperation,
    values: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError("App API parameters are missing or invalid.")
    if not set(values).issubset(_PARAMETER_KEYS[operation]):
        raise ValueError("App API parameters contain an unreviewed field.")
    result = dict(values)
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("App API parameter type is invalid.")
        if isinstance(value, str) and (not value or len(value) > 200):
            raise ValueError("App API string parameter is invalid.")
        if isinstance(value, int) and value < 0:
            raise ValueError("App API numeric parameter is invalid.")
        if any(fragment in key.lower() for fragment in ("token", "cookie", "password")):
            raise ValueError("Secret-shaped App API parameter is forbidden.")
    required = {
        PixivAppApiOperation.SEARCH_ILLUST: "word",
        PixivAppApiOperation.USER_ILLUSTS: "user_id",
        PixivAppApiOperation.ILLUST_RANKING: "mode",
    }[operation]
    if required not in result:
        raise ValueError("App API operation identity parameter is missing.")
    return result


def _required_string(value: object) -> str:
    if not isinstance(value, str):
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    return value


def _required_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    return value


def _required_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    return parsed


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise PixivAppApiError("pixiv_app_api_record_schema_invalid")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect bounded Pixiv App API metadata into a non-canonical candidate."
    )
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--proxy", choices=("http://127.0.0.1:41080",), default=None)
    parser.add_argument(
        "--auth-mode",
        choices=("oauth-pkce", "refresh-token"),
        default="oauth-pkce",
    )
    parser.add_argument(
        "--callback-mode",
        choices=("automatic", "hidden-paste"),
        default="automatic",
    )
    parser.add_argument("--g0", type=Path, default=Path("config/g0_approval.json"))
    parser.add_argument(
        "--policy", type=Path, default=Path("config/pixiv_app_api_policy.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/candidates/pixiv-app-api.candidate.jsonl"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/reports/pixiv-app-api-collection.json"),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--confirm", choices=("UNOFFICIAL-APP-API",), required=True)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    search = subparsers.add_parser("search", help="Search illustration metadata by tag/word.")
    search.add_argument("word")
    author = subparsers.add_parser("author", help="Read one author's illustration pages.")
    author.add_argument("user_id", type=int)
    ranking = subparsers.add_parser("ranking", help="Read one ranking sequence.")
    ranking.add_argument("mode")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    oauth_code_requested = False
    refresh_token_requested = False
    external_network_used = False
    operation_name = "unknown"
    if (args.output.exists() or args.report.exists()) and not args.force:
        print("output_exists", file=sys.stderr)
        return 2
    try:
        approval = load_active_g0_approval(args.g0.resolve())
        policy = load_pixiv_app_api_policy(args.policy.resolve())
        validate_pixiv_app_api_boundary(policy, approval)
        operation, parameters = _cli_operation(args)
        operation_name = operation.value
        _validate_parameters(operation, parameters)
        if not 1 <= args.max_pages <= policy.max_pages_per_run:
            raise ValueError("Requested page limit is outside the reviewed policy.")
        authentication_mode: Literal["oauth_pkce", "runtime_refresh_token"]
        if args.auth_mode == "oauth-pkce":
            authentication_mode = "oauth_pkce"
            if args.proxy != "http://127.0.0.1:41080":
                raise ValueError("OAuth PKCE requires the reviewed local Pixiv proxy.")
            project_root = Path(__file__).resolve().parents[4]
            oauth_code_requested = True
            external_network_used = True
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text("", encoding="utf-8")
            _write_json(
                args.report,
                {
                    "status": "awaiting_user_login",
                    "generated_at": datetime.now(UTC).isoformat(),
                    "operation": operation_name,
                    "authentication_mode": authentication_mode,
                    "requested_pages": 0,
                    "input_records": 0,
                    "candidate_records": 0,
                    "duplicate_records": 0,
                    "skipped_records": 0,
                    "external_network_used": True,
                    "oauth_authorization_code_requested": True,
                    "refresh_token_requested": False,
                    "password_requested": False,
                    "secret_persisted": False,
                    "raw_payload_persisted": False,
                    "media_persisted": False,
                    "automatic_retries": 0,
                    "network_concurrency": 1,
                    "canonical_ingest_authorized": False,
                    "violations": [],
                },
            )
            with open_runtime_oauth_session(
                proxy=args.proxy,
                callback_reader=getpass,
                launcher=project_root / "scripts" / "start-pixiv-browser.ps1",
                callback_mode=args.callback_mode.replace("-", "_"),
            ) as session:
                client = PixivPy3Client.authenticate_access_token(
                    session,
                    proxy=args.proxy,
                )
        else:
            authentication_mode = "runtime_refresh_token"
            refresh_token_requested = True
            with OperatorSessionFactory().open(
                ttl_minutes=10,
                prompt="Paste the Pixiv refresh token locally (input hidden; never stored): ",
            ) as session:
                external_network_used = True
                client = PixivPy3Client.authenticate(session, proxy=args.proxy)
        collector = PixivAppApiCollector(
            client,
            policy,
            approval,
            authentication_mode=authentication_mode,
        )
        collection = collector.collect(
            operation,
            parameters,
            max_pages=args.max_pages,
        )
    except (OSError, ValueError, PixivAppApiError, PixivOAuthPkceError):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("", encoding="utf-8")
        _write_json(
            args.report,
            {
                "status": "blocked",
                "generated_at": datetime.now(UTC).isoformat(),
                "operation": operation_name,
                "authentication_mode": (
                    "oauth_pkce" if args.auth_mode == "oauth-pkce" else "runtime_refresh_token"
                ),
                "requested_pages": 0,
                "input_records": 0,
                "candidate_records": 0,
                "duplicate_records": 0,
                "skipped_records": 0,
                "external_network_used": external_network_used,
                "canonical_ingest_authorized": False,
                "oauth_authorization_code_requested": oauth_code_requested,
                "refresh_token_requested": refresh_token_requested,
                "password_requested": False,
                "secret_persisted": False,
                "raw_payload_persisted": False,
                "media_persisted": False,
                "automatic_retries": 0,
                "network_concurrency": 1,
                "violation": "pixiv_app_api_collection_failed",
                "violations": ["pixiv_app_api_collection_failed"],
            },
        )
        print("pixiv_app_api_collection_failed", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            + "\n"
            for record in collection.records
        ),
        encoding="utf-8",
    )
    _write_json(args.report, asdict(collection.report))
    print(json.dumps(asdict(collection.report), ensure_ascii=False, sort_keys=True))
    return 0 if collection.report.status == "candidate_ready" else 2


def _cli_operation(
    args: argparse.Namespace,
) -> tuple[PixivAppApiOperation, dict[str, object]]:
    if args.operation == "search":
        return PixivAppApiOperation.SEARCH_ILLUST, {"word": args.word}
    if args.operation == "author":
        return PixivAppApiOperation.USER_ILLUSTS, {
            "user_id": args.user_id,
            "type": "illust",
        }
    if args.operation == "ranking":
        return PixivAppApiOperation.ILLUST_RANKING, {"mode": args.mode}
    raise ValueError("App API operation is invalid.")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
