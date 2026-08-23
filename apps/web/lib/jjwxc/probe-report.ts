import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

export interface JjwxcProbeView {
  status: "dry_run" | "candidate_ready" | "blocked";
  candidateCount: number;
  requestCount: number;
  canonicalIngestAuthorized: false;
}

function reportDirectory(): string {
  const configured = process.env.PYURI_PHASE6_REPORT_DIR;
  if (configured) {
    if (configured !== "/run/pyuri-reports") throw new Error("probe report directory is outside the reviewed container boundary");
    return configured;
  }
  return path.resolve(process.cwd(), "../../var/reports");
}

export async function loadJjwxcProbeView(): Promise<JjwxcProbeView> {
  const payload: unknown = JSON.parse(await readFile(path.join(reportDirectory(), "jjwxc-public-probe.json"), "utf8"));
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("probe report must be an object");
  const report = payload as Record<string, unknown>;
  const status = report.status;
  if (status !== "dry_run" && status !== "candidate_ready" && status !== "blocked") throw new Error("probe status invalid");
  const candidateCount = status === "candidate_ready" && Number.isInteger(report.candidate_count) ? Number(report.candidate_count) : 0;
  const requestCount = status === "candidate_ready" && Number.isInteger(report.request_count) ? Number(report.request_count) : 0;
  if (candidateCount < 0 || candidateCount > 1 || requestCount < 0 || requestCount > 1 || report.canonical_ingest_authorized !== false) throw new Error("probe report exceeds one-request boundary");
  return { status, candidateCount, requestCount, canonicalIngestAuthorized: false };
}
