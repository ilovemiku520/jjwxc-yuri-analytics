import { describe, expect, it } from "vitest";

import {
  AUTHOR_V_JOB_REPORT_FORMAT,
  buildAuthorVFailedCsv,
  buildAuthorVJobReport,
} from "../lib/jjwxc/author-v-report";
import type { JjwxcAuthorVClickJobResponse } from "../types/api";

const jobs: JjwxcAuthorVClickJobResponse[] = [
  { job_id: 9, status: "failed", task_status: "failed", attempt_count: 2, record_count: 40, last_error_code: "vip_chapter_set_incomplete", novel_ids: ["88", "77"] },
  { job_id: 8, status: "completed", task_status: "succeeded", attempt_count: 1, record_count: 20, last_error_code: null, novel_ids: ["66"] },
];

describe("author V click job report", () => {
  it("summarizes durable jobs without exporting click values", () => {
    const report = buildAuthorVJobReport(jobs, "2026-08-24T08:00:00.000Z");
    expect(report.source_format).toBe(AUTHOR_V_JOB_REPORT_FORMAT);
    expect(report.contains_click_values).toBe(false);
    expect(report.summary).toMatchObject({ job_count: 2, record_count: 60, completed_record_count: 20, failed_record_count: 40 });
    expect(report.jobs.map((item) => item.job_id)).toEqual([8, 9]);
    expect(JSON.stringify(report)).not.toContain("click_count");
  });

  it("exports only failed jobs as a spreadsheet-friendly CSV", () => {
    const csv = buildAuthorVFailedCsv(jobs);
    expect(csv).toContain("9,77|88,40,2,vip_chapter_set_incomplete");
    expect(csv).not.toContain("8,66");
  });
});
