import { postApi } from "../../../../../../lib/api/client";
import type { JjwxcAuthorVClickJobResponse } from "../../../../../../types/api";

export const dynamic = "force-dynamic";

export async function POST(_request: Request, context: { params: Promise<{ jobId: string }> }): Promise<Response> {
  const { jobId } = await context.params;
  if (!/^[1-9][0-9]{0,18}$/u.test(jobId)) return Response.json({ detail: "job_id_invalid" }, { status: 422 });
  try {
    const result = await postApi<JjwxcAuthorVClickJobResponse>(`/api/v1/jjwxc/analytics/author-v-clicks/jobs/${jobId}/retry`, {});
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ detail: "job_retry_unavailable" }, { status: 409 });
  }
}
