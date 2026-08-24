import type { JjwxcAuthorVClickJobResponse } from "../../types/api";

export const AUTHOR_V_JOB_REPORT_FORMAT = "pyuri_jjwxc_author_v_job_report";

export function buildAuthorVJobReport(
  jobs: JjwxcAuthorVClickJobResponse[],
  generatedAt = new Date().toISOString(),
) {
  const ordered = [...jobs].sort((left, right) => left.job_id - right.job_id);
  const count = (status: JjwxcAuthorVClickJobResponse["status"]) =>
    ordered.filter((item) => item.status === status).length;
  const records = (status: JjwxcAuthorVClickJobResponse["status"]) =>
    ordered.filter((item) => item.status === status).reduce((sum, item) => sum + item.record_count, 0);
  return {
    source_format: AUTHOR_V_JOB_REPORT_FORMAT,
    schema_version: 1 as const,
    generated_at: generatedAt,
    contains_click_values: false as const,
    summary: {
      job_count: ordered.length,
      record_count: ordered.reduce((sum, item) => sum + item.record_count, 0),
      completed_job_count: count("completed"),
      pending_job_count: count("pending"),
      running_job_count: count("running"),
      failed_job_count: count("failed"),
      completed_record_count: records("completed"),
      failed_record_count: records("failed"),
    },
    jobs: ordered.map((item) => ({
      job_id: item.job_id,
      novel_ids: [...item.novel_ids].sort((left, right) => Number(left) - Number(right)),
      status: item.status,
      task_status: item.task_status,
      record_count: item.record_count,
      attempt_count: item.attempt_count,
      last_error_code: item.last_error_code,
    })),
  };
}

function csvCell(value: string | number | null) {
  const text = value === null ? "" : String(value);
  return /[",\r\n]/u.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function buildAuthorVFailedCsv(jobs: JjwxcAuthorVClickJobResponse[]) {
  const rows: Array<Array<string | number | null>> = [
    ["job_id", "novel_ids", "record_count", "attempt_count", "error_code"],
    ...jobs
      .filter((item) => item.status === "failed")
      .sort((left, right) => left.job_id - right.job_id)
      .map((item) => [
        item.job_id,
        [...item.novel_ids].sort((left, right) => Number(left) - Number(right)).join("|"),
        item.record_count,
        item.attempt_count,
        item.last_error_code,
      ]),
  ];
  return `${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
}
