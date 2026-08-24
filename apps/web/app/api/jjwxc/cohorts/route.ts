import { postApi } from "../../../../lib/api/client";
import type { JjwxcCohortImportResponse } from "../../../../types/api";

export const dynamic = "force-dynamic";

type RequestPayload = {
  mode?: unknown;
  novel_ids?: unknown;
};

function hasValidSameOrigin(
  origin: string | null,
  host: string | null,
): boolean {
  if (!origin) return true;
  if (!host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export async function POST(request: Request): Promise<Response> {
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (contentLength > 16_384) {
    return Response.json(
      { detail: "cohort_request_too_large" },
      { status: 413 },
    );
  }
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!hasValidSameOrigin(origin, host)) {
    return Response.json(
      { detail: "cohort_cross_origin_forbidden" },
      { status: 403 },
    );
  }
  let payload: RequestPayload;
  try {
    const body = await request.text();
    if (new TextEncoder().encode(body).byteLength > 16_384) {
      return Response.json(
        { detail: "cohort_request_too_large" },
        { status: 413 },
      );
    }
    payload = JSON.parse(body) as RequestPayload;
  } catch {
    return Response.json(
      { detail: "cohort_request_invalid_json" },
      { status: 400 },
    );
  }
  const mode =
    payload.mode === "status"
      ? "status"
      : payload.mode === "queue"
        ? "queue"
        : null;
  const novelIds = Array.isArray(payload.novel_ids) ? payload.novel_ids : [];
  if (
    mode === null ||
    novelIds.length < 1 ||
    novelIds.length > 100 ||
    novelIds.some(
      (value) =>
        typeof value !== "string" || !/^[1-9][0-9]{0,11}$/u.test(value),
    )
  ) {
    return Response.json({ detail: "cohort_request_invalid" }, { status: 422 });
  }
  try {
    const result = await postApi<JjwxcCohortImportResponse>(
      "/api/v1/jjwxc/analytics/cohorts/import",
      { mode, novel_ids: novelIds },
    );
    return Response.json(result, {
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return Response.json(
      { detail: "cohort_service_unavailable" },
      { status: 503 },
    );
  }
}
