import { fetchInternalApi } from "../../../../../lib/api/client";
import type { JjwxcAuthorVClickJobResponse } from "../../../../../types/api";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ jobId: string }> }): Promise<Response> {
  const { jobId } = await context.params;
  if (!/^[1-9][0-9]{0,18}$/u.test(jobId)) return Response.json({ detail: "job_id_invalid" }, { status: 422 });
  try {
    const result = await fetchInternalApi<JjwxcAuthorVClickJobResponse>(`/api/v1/jjwxc/analytics/author-v-clicks/jobs/${jobId}`);
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ detail: "job_status_unavailable" }, { status: 503 });
  }
}
