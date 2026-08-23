import "server-only";

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

export interface BrowserExportImportViewData {
  status: "candidate_ready" | "blocked";
  sourceFormat: "powerful_pixiv_downloader_json" | "pyuri_pixiv_browser_companion_json";
  generatedAt: string;
  inputFiles: number;
  inputRecords: number;
  acceptedRecords: number;
  rejectedRecords: number;
  skippedRecords: number;
  violations: string[];
  canonicalIngestAuthorized: false;
  reportSha256: string;
}

export interface CandidateImportReviewViewData {
  status: "authorized_for_canonical_ingest" | "blocked";
  candidateRecordCount: number;
  manualVisibilityReviewVerified: boolean;
  sourceEndpointContractReady: boolean;
  canonicalIngestAuthorized: boolean;
  violations: string[];
  importReportSha256: string;
}

export interface PixivAppApiCollectionViewData {
  status: "awaiting_user_login" | "candidate_ready" | "blocked";
  generatedAt: string;
  operation: "search_illust" | "user_illusts" | "illust_ranking" | "unknown";
  authenticationMode: "oauth_pkce" | "runtime_refresh_token";
  requestedPages: number;
  inputRecords: number;
  candidateRecords: number;
  duplicateRecords: number;
  skippedRecords: number;
  externalNetworkUsed: boolean;
  violations: string[];
}

function reportDirectory(): string {
  const configured = process.env.PYURI_PHASE6_REPORT_DIR;
  if (configured) {
    if (configured !== "/run/pyuri-reports") {
      throw new Error("Import report directory is outside the reviewed container boundary");
    }
    return configured;
  }
  return path.resolve(process.cwd(), "../../var/reports");
}

function count(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new Error("Import report count is invalid");
  }
  return Number(value);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`)
      .join(",")}}`;
  }
  const primitive = JSON.stringify(value);
  if (primitive === undefined) {
    throw new Error("Report contains a non-JSON value");
  }
  return primitive;
}

function sha256Json(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

export async function loadBrowserExportImportView(): Promise<BrowserExportImportViewData> {
  const payload: unknown = JSON.parse(
    await readFile(
      path.join(/* turbopackIgnore: true */ reportDirectory(), "browser-export-import.json"),
      "utf8",
    ),
  );
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Import report must be an object");
  }
  const report = payload as Record<string, unknown>;
  const status = report.status;
  const sourceFormat = report.source_format;
  const violations = report.violations;
  const generatedAt = report.generated_at;
  if ((status !== "candidate_ready" && status !== "blocked") ||
      (sourceFormat !== "powerful_pixiv_downloader_json" &&
       sourceFormat !== "pyuri_pixiv_browser_companion_json") ||
      typeof generatedAt !== "string" || Number.isNaN(Date.parse(generatedAt)) ||
      !Array.isArray(violations) ||
      violations.some((item) => typeof item !== "string" || !/^[a-z0-9_]{1,80}$/.test(item)) ||
      report.visibility_verified !== false ||
      report.canonical_ingest_authorized !== false ||
      report.credentials_requested !== false ||
      report.external_network_used !== false ||
      report.media_persisted !== false ||
      report.raw_payload_persisted !== false) {
    throw new Error("Import report failed its safe display contract");
  }
  const inputFiles = count(report.input_files ?? 1);
  const inputRecords = count(report.input_records);
  const acceptedRecords = count(report.accepted_records);
  const rejectedRecords = count(report.rejected_records);
  const skippedRecords = count(report.duplicate_or_extra_page_records);
  if (inputRecords !== acceptedRecords + rejectedRecords + skippedRecords) {
    throw new Error("Import report counts are inconsistent");
  }
  if (inputFiles < 1 || inputFiles > 25) {
    throw new Error("Import report file count is outside the bounded range");
  }
  if (status === "candidate_ready" &&
      (acceptedRecords === 0 || rejectedRecords !== 0 || violations.length !== 0)) {
    throw new Error("Candidate-ready import report is inconsistent");
  }
  return {
    status,
    sourceFormat,
    generatedAt,
    inputFiles,
    inputRecords,
    acceptedRecords,
    rejectedRecords,
    skippedRecords,
    violations: violations as string[],
    canonicalIngestAuthorized: false,
    reportSha256: sha256Json(report),
  };
}

export async function loadCandidateImportReviewView(): Promise<CandidateImportReviewViewData> {
  const payload: unknown = JSON.parse(
    await readFile(
      path.join(/* turbopackIgnore: true */ reportDirectory(), "candidate-import-review.json"),
      "utf8",
    ),
  );
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Candidate review report must be an object");
  }
  const report = payload as Record<string, unknown>;
  const status = report.status;
  const violations = report.violations;
  const importReportSha256 = report.import_report_sha256;
  if ((status !== "authorized_for_canonical_ingest" && status !== "blocked") ||
      !Array.isArray(violations) ||
      violations.some((item) => typeof item !== "string" || !/^[a-z0-9_]{1,80}$/.test(item)) ||
      typeof report.manual_visibility_review_verified !== "boolean" ||
      typeof report.source_endpoint_contract_ready !== "boolean" ||
      typeof report.canonical_ingest_authorized !== "boolean" ||
      typeof importReportSha256 !== "string" || !/^[a-f0-9]{64}$/.test(importReportSha256) ||
      report.credentials_requested !== false ||
      report.external_network_used !== false ||
      report.media_persisted !== false ||
      report.raw_payload_persisted !== false) {
    throw new Error("Candidate review report failed its safe display contract");
  }
  const candidateRecordCount = count(report.candidate_record_count);
  const canonicalIngestAuthorized = report.canonical_ingest_authorized;
  if ((status === "authorized_for_canonical_ingest") !== canonicalIngestAuthorized ||
      (canonicalIngestAuthorized && violations.length !== 0)) {
    throw new Error("Candidate review decision is inconsistent");
  }
  return {
    status,
    candidateRecordCount,
    manualVisibilityReviewVerified: report.manual_visibility_review_verified,
    sourceEndpointContractReady: report.source_endpoint_contract_ready,
    canonicalIngestAuthorized,
    violations: violations as string[],
    importReportSha256,
  };
}

export async function loadPixivAppApiCollectionView(): Promise<PixivAppApiCollectionViewData> {
  const payload: unknown = JSON.parse(
    await readFile(
      path.join(/* turbopackIgnore: true */ reportDirectory(), "pixiv-app-api-collection.json"),
      "utf8",
    ),
  );
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("App API report must be an object");
  }
  const report = payload as Record<string, unknown>;
  const status = report.status;
  const generatedAt = report.generated_at;
  const operation = report.operation;
  const authenticationMode = report.authentication_mode;
  const violations = report.violations;
  if ((status !== "awaiting_user_login" && status !== "candidate_ready" &&
       status !== "blocked") ||
      typeof generatedAt !== "string" || Number.isNaN(Date.parse(generatedAt)) ||
      (operation !== "search_illust" && operation !== "user_illusts" &&
       operation !== "illust_ranking" && operation !== "unknown") ||
      (authenticationMode !== "oauth_pkce" && authenticationMode !== "runtime_refresh_token") ||
      !Array.isArray(violations) ||
      violations.some((item) => typeof item !== "string" || !/^[a-z0-9_]{1,80}$/.test(item)) ||
      typeof report.external_network_used !== "boolean" ||
      report.password_requested !== false ||
      report.secret_persisted !== false ||
      report.raw_payload_persisted !== false ||
      report.media_persisted !== false ||
      report.automatic_retries !== 0 ||
      report.network_concurrency !== 1 ||
      report.canonical_ingest_authorized !== false) {
    throw new Error("App API report failed its safe display contract");
  }
  const requestedPages = count(report.requested_pages);
  const inputRecords = count(report.input_records);
  const candidateRecords = count(report.candidate_records);
  const duplicateRecords = count(report.duplicate_records);
  const skippedRecords = count(report.skipped_records);
  if (requestedPages > 100 || inputRecords > 3_000 || candidateRecords > 3_000 ||
      inputRecords !== candidateRecords + duplicateRecords + skippedRecords ||
      (status === "candidate_ready" && (requestedPages === 0 || candidateRecords === 0 ||
       violations.length !== 0))) {
    throw new Error("App API report counts are inconsistent");
  }
  return {
    status,
    generatedAt,
    operation,
    authenticationMode,
    requestedPages,
    inputRecords,
    candidateRecords,
    duplicateRecords,
    skippedRecords,
    externalNetworkUsed: report.external_network_used,
    violations: violations as string[],
  };
}
