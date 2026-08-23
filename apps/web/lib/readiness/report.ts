import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

export interface ReadinessControl {
  name: string;
  passed: boolean;
  evidence: string;
  blocker: string | null;
}

export interface ReadinessViewData {
  phase: number;
  completion: number;
  status: string;
  generatedAt: string;
  passedCount: number;
  controlCount: number;
  controls: ReadinessControl[];
  backup: {
    status: string;
    rows: number;
    schemaVersion: string;
    checksumVerified: boolean;
  };
  production: {
    status: string;
    unresolvedCount: number;
    identityReviewed: boolean;
    tlsReviewed: boolean;
  };
  publicationBinding: { status: string; unresolvedCount: number; matchedCount: number };
  externalPublicationApproved: false;
  realSourceCollectionAuthorized: false;
}

function reportDirectory(): string {
  const configured = process.env.PYURI_PHASE6_REPORT_DIR;
  if (configured) {
    if (configured !== "/run/pyuri-reports") {
      throw new Error("Phase 6 report directory is outside the reviewed container boundary");
    }
    return configured;
  }
  return path.resolve(process.cwd(), "../../var/reports");
}

async function readObject(fileName: string): Promise<Record<string, unknown>> {
  const value: unknown = JSON.parse(
    await readFile(
      path.join(/* turbopackIgnore: true */ reportDirectory(), fileName),
      "utf8",
    ),
  );
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Phase 6 report must be an object");
  }
  return value as Record<string, unknown>;
}

export async function loadReadinessView(): Promise<ReadinessViewData> {
  const [readiness, backup, production, publicationBinding] = await Promise.all([
    readObject("phase6_readiness.json"),
    readObject("phase6_backup_restore.json"),
    readObject("production_identity_tls_review.json"),
    readObject("production_publication_binding.json"),
  ]);
  const controls = readiness.controls;
  const violations = production.violations;
  const bindingViolations = publicationBinding.violations;
  const matchedFields = publicationBinding.matched_fields;
  if (!Array.isArray(controls) || !Array.isArray(violations) ||
      !Array.isArray(bindingViolations) || !Array.isArray(matchedFields)) {
    throw new Error("Phase 6 report arrays are missing");
  }
  return {
    phase: Number(readiness.phase),
    completion: Number(readiness.estimated_completion_percent),
    status: String(readiness.status),
    generatedAt: String(readiness.generated_at),
    passedCount: Number(readiness.passed_control_count),
    controlCount: Number(readiness.control_count),
    controls: controls.map((control) => {
      const item = control as Record<string, unknown>;
      return {
        name: String(item.name),
        passed: item.passed === true,
        evidence: String(item.evidence),
        blocker: item.blocker === null ? null : String(item.blocker),
      };
    }),
    backup: {
      status: String(backup.status),
      rows: Number(backup.restored_row_count),
      schemaVersion: String(backup.schema_version),
      checksumVerified: backup.backup_sha256_verified === true,
    },
    production: {
      status: String(production.status),
      unresolvedCount: violations.length,
      identityReviewed: production.identity_reviewed === true,
      tlsReviewed: production.tls_reviewed === true,
    },
    publicationBinding: {
      status: String(publicationBinding.status),
      unresolvedCount: bindingViolations.length,
      matchedCount: matchedFields.length,
    },
    externalPublicationApproved: false,
    realSourceCollectionAuthorized: false,
  };
}
