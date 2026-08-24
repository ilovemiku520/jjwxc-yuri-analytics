import { postApi } from "../../../../lib/api/client";
import type { JjwxcAuthorVClickJobResponse } from "../../../../types/api";

export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 512 * 1024;

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  const host = request.headers.get("host");
  if (!host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export async function POST(request: Request): Promise<Response> {
  if (!sameOrigin(request)) {
    return Response.json({ detail: "author_v_import_cross_origin_forbidden" }, { status: 403 });
  }
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (declaredLength > MAX_BODY_BYTES) {
    return Response.json({ detail: "author_v_import_too_large" }, { status: 413 });
  }
  let body: string;
  try {
    body = await request.text();
  } catch {
    return Response.json({ detail: "author_v_import_body_invalid" }, { status: 400 });
  }
  if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) {
    return Response.json({ detail: "author_v_import_too_large" }, { status: 413 });
  }
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    return Response.json({ detail: "author_v_import_json_invalid" }, { status: 400 });
  }
  try {
    const result = await postApi<JjwxcAuthorVClickJobResponse>(
      "/api/v1/jjwxc/analytics/author-v-clicks/jobs",
      payload,
    );
    return Response.json(result, {
      headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
    });
  } catch {
    return Response.json({ detail: "author_v_import_service_unavailable" }, { status: 503 });
  }
}
