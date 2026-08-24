"use client";

import { useEffect, useState } from "react";

import {
  buildAuthorVFailedCsv,
  buildAuthorVJobReport,
} from "../../lib/jjwxc/author-v-report";
import type { JjwxcAuthorVClickJobResponse } from "../../types/api";

type ExportRecord = { novel_id: string; chapter_id: number; click_count: number };
type AuthorExport = {
  source_format: "pyuri_jjwxc_author_v_clicks_json";
  schema_version: 1;
  generated_at: string;
  authorization_attestation: true;
  records: ExportRecord[];
};

const MAX_FILE_BYTES = 512 * 1024;
const MAX_FILE_COUNT = 500;
const MAX_TOTAL_FILE_BYTES = 50 * 1024 * 1024;
const MAX_TOTAL_RECORDS = 100_000;
const MAX_BATCH_RECORDS = 2_000;
const MAX_BATCH_NOVELS = 20;

const ERROR_LABELS: Record<string, string> = {
  novel_not_collected: "作品尚未完成公开元数据采集",
  novel_snapshot_missing: "作品快照缺失",
  chapter_snapshot_missing: "章节快照缺失",
  vip_chapter_mismatch: "提交中包含非 V 章节或章节不匹配",
  vip_chapter_set_incomplete: "V 章节集合不完整",
  worker_lease_expired: "任务执行超时，可重试",
  job_failed: "任务处理失败",
};

function downloadText(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function parseExport(value: unknown): AuthorExport {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("文件结构无效");
  const item = value as Record<string, unknown>;
  if (item.source_format !== "pyuri_jjwxc_author_v_clicks_json" || item.schema_version !== 1) {
    throw new Error("不是本项目作者后台扩展生成的文件");
  }
  if (item.authorization_attestation !== true) throw new Error("缺少作者授权确认");
  if (typeof item.generated_at !== "string" || Number.isNaN(Date.parse(item.generated_at))) {
    throw new Error("采集时间无效");
  }
  if (!Array.isArray(item.records) || item.records.length < 1 || item.records.length > 2_000) {
    throw new Error("记录数必须在 1–2000 条之间");
  }
  for (const record of item.records) {
    if (!record || typeof record !== "object" || Array.isArray(record)) throw new Error("记录结构无效");
    const row = record as Record<string, unknown>;
    if (typeof row.novel_id !== "string" || !/^[1-9][0-9]{0,11}$/u.test(row.novel_id)) {
      throw new Error("作品 ID 无效");
    }
    if (!Number.isSafeInteger(row.chapter_id) || Number(row.chapter_id) < 1) {
      throw new Error("章节 ID 无效");
    }
    if (!Number.isSafeInteger(row.click_count) || Number(row.click_count) < 0) {
      throw new Error("V 点击必须是非负整数");
    }
  }
  return item as AuthorExport;
}

export function AuthorVClickImporter() {
  const [payloads, setPayloads] = useState<AuthorExport[]>([]);
  const [fileSummary, setFileSummary] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<JjwxcAuthorVClickJobResponse[]>([]);

  function buildBatches(exports: AuthorExport[]): AuthorExport[] {
    const novels = new Map<string, { generatedAt: string; records: Map<number, ExportRecord> }>();
    for (const item of exports) {
      for (const record of item.records) {
        const group = novels.get(record.novel_id) ?? { generatedAt: item.generated_at, records: new Map() };
        if (Date.parse(item.generated_at) > Date.parse(group.generatedAt)) group.generatedAt = item.generated_at;
        group.records.set(record.chapter_id, record);
        novels.set(record.novel_id, group);
      }
    }
    const batches: AuthorExport[] = [];
    let records: ExportRecord[] = [];
    let generatedAt = "";
    let novelCount = 0;
    const flush = () => {
      if (!records.length) return;
      batches.push({ source_format: "pyuri_jjwxc_author_v_clicks_json", schema_version: 1, generated_at: generatedAt, authorization_attestation: true, records });
      records = [];
      generatedAt = "";
      novelCount = 0;
    };
    for (const group of novels.values()) {
      const novelRecords = [...group.records.values()];
      if (novelRecords.length > MAX_BATCH_RECORDS) throw new Error("单部作品超过 2000 个 V 章节，暂不能安全导入");
      if (novelCount >= MAX_BATCH_NOVELS || records.length + novelRecords.length > MAX_BATCH_RECORDS) flush();
      records.push(...novelRecords);
      novelCount += 1;
      if (!generatedAt || Date.parse(group.generatedAt) > Date.parse(generatedAt)) generatedAt = group.generatedAt;
    }
    flush();
    return batches;
  }

  async function chooseFiles(files?: FileList | null) {
    setPayloads([]);
    setJobs([]);
    setError("");
    setFileSummary("");
    const selected = files ? [...files] : [];
    if (!selected.length) return;
    if (selected.length > MAX_FILE_COUNT) return setError(`一次最多选择 ${MAX_FILE_COUNT} 个文件`);
    if (selected.some((file) => !file.name.toLowerCase().endsWith(".json"))) return setError("仅支持扩展生成的 JSON 文件");
    if (selected.some((file) => file.size > MAX_FILE_BYTES)) return setError("每个文件不能超过 512 KiB");
    if (selected.reduce((sum, file) => sum + file.size, 0) > MAX_TOTAL_FILE_BYTES) return setError("本批文件总大小不能超过 50 MiB");
    try {
      const parsed = await Promise.all(selected.map(async (file) => parseExport(JSON.parse(await file.text()) as unknown)));
      const totalRecords = parsed.reduce((sum, item) => sum + item.records.length, 0);
      if (totalRecords > MAX_TOTAL_RECORDS) throw new Error("本批记录不能超过 100,000 条");
      const batches = buildBatches(parsed);
      setPayloads(batches);
      setFileSummary(`${selected.length} 个文件 · ${totalRecords} 条原始记录 · ${batches.length} 个提交批次`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法解析文件");
    }
  }

  async function submit() {
    if (!payloads.length) return;
    setBusy(true);
    setError("");
    try {
      const responses: JjwxcAuthorVClickJobResponse[] = [];
      let cursor = 0;
      const workers = Array.from({ length: Math.min(4, payloads.length) }, async () => {
        while (cursor < payloads.length) {
          const batch = payloads[cursor++];
          const response = await fetch("/api/jjwxc/author-v-clicks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(batch) });
          if (!response.ok) throw new Error("批量导入被中止，请确认作品均已先完成公开采集");
          responses.push((await response.json()) as JjwxcAuthorVClickJobResponse);
        }
      });
      await Promise.all(workers);
      setJobs(responses);
      localStorage.setItem("pyuri-author-v-jobs", JSON.stringify(responses.map((item) => item.job_id)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    try {
      const restored = JSON.parse(localStorage.getItem("pyuri-author-v-jobs") ?? "[]") as unknown;
      if (Array.isArray(restored) && restored.every((item) => Number.isSafeInteger(item) && Number(item) > 0)) {
        void refreshJobs(restored as number[]);
      }
    } catch { localStorage.removeItem("pyuri-author-v-jobs"); }
  }, []);

  useEffect(() => {
    if (!jobs.some((item) => item.status === "pending" || item.status === "running")) return;
    const timer = window.setInterval(() => void refreshJobs(jobs.map((item) => item.job_id)), 2_000);
    return () => window.clearInterval(timer);
  }, [jobs]);

  async function refreshJobs(jobIds: number[]) {
    const refreshed = await Promise.all(jobIds.map(async (jobId) => {
      const response = await fetch(`/api/jjwxc/author-v-clicks/${jobId}`, { cache: "no-store" });
      if (!response.ok) throw new Error("job_status_unavailable");
      return (await response.json()) as JjwxcAuthorVClickJobResponse;
    }));
    setJobs(refreshed);
  }

  async function retryJob(jobId: number) {
    const response = await fetch(`/api/jjwxc/author-v-clicks/${jobId}/retry`, { method: "POST" });
    if (!response.ok) return setError("该任务已达到重试上限或当前不可重试");
    const retried = (await response.json()) as JjwxcAuthorVClickJobResponse;
    setJobs((items) => items.map((item) => item.job_id === jobId ? retried : item));
  }

  function downloadJobReport() {
    const generatedAt = new Date().toISOString();
    const report = buildAuthorVJobReport(jobs, generatedAt);
    downloadText(
      `pyuri-author-v-import-report-${generatedAt.replaceAll(":", "-")}.json`,
      `${JSON.stringify(report, null, 2)}\n`,
      "application/json;charset=utf-8",
    );
  }

  function downloadFailedJobs() {
    const generatedAt = new Date().toISOString();
    downloadText(
      `pyuri-author-v-failed-jobs-${generatedAt.replaceAll(":", "-")}.csv`,
      `\uFEFF${buildAuthorVFailedCsv(jobs)}`,
      "text/csv;charset=utf-8",
    );
  }

  return (
    <section className="state-panel" aria-labelledby="author-v-import-title">
      <div className="panel-heading">
        <div><p className="eyebrow">AUTHOR-OWNED METRICS</p><h2 id="author-v-import-title">作者授权 V 点击导入</h2></div>
        <span>LOCAL JSON</span>
      </div>
      <p>扩展支持逐页收集、浏览器重启后继续及合并去重导出；最小记录仅在本机暂存 24 小时。它不读取正文、密码、Cookie 或读者身份。作品必须已在本项目完成公开元数据采集。</p>
      <div className="cohort-file-controls">
        <label><span>选择一批扩展 JSON</span><input accept=".json,application/json" multiple type="file" onChange={(event) => void chooseFiles(event.target.files)} /></label>
        <button type="button" disabled={!payloads.length || busy} onClick={() => void submit()}>{busy ? "正在并行导入…" : "校验、分批并导入 V 点击"}</button>
        <a href="/downloads/jjwxc-author-v-click-companion.zip" download>下载作者后台辅助扩展</a>
      </div>
      {payloads.length ? <p role="status">{fileSummary}；按作品合并重复章节后，以最多 4 路并行提交。</p> : null}
      {jobs.length ? <div className="cohort-import-summary" role="status">
        <p>持久化任务 {jobs.length} 个：完成 {jobs.filter((item) => item.status === "completed").length} · 处理中 {jobs.filter((item) => item.status === "pending" || item.status === "running").length} · 失败 {jobs.filter((item) => item.status === "failed").length}；共 {jobs.reduce((sum, item) => sum + item.record_count, 0)} 条记录。提交完成后可以关闭页面，重新打开会自动恢复进度。</p>
        <div className="cohort-import-actions">
          <button type="button" onClick={downloadJobReport}>下载完整任务报告 JSON</button>
          <button type="button" disabled={!jobs.some((item) => item.status === "failed")} onClick={downloadFailedJobs}>下载失败任务 CSV</button>
        </div>
        {jobs.filter((item) => item.status === "failed").map((item) => <p key={item.job_id}>任务 {item.job_id} · 作品 {item.novel_ids.join("、") || "未知"}：{ERROR_LABELS[item.last_error_code ?? "job_failed"] ?? item.last_error_code ?? "任务失败"}（尝试 {item.attempt_count}/3） <button type="button" onClick={() => void retryJob(item.job_id)}>重试</button></p>)}
      </div> : null}
      {error ? <p className="cohort-import-error" role="alert">{error}</p> : null}
      <details className="statistics-details"><summary>授权、容量与完整性要求</summary><div><ul><li>仅可导出你本人拥有管理权限的作品后台数据。</li><li>一次可选择 500 个文件、合计 50 MiB / 100,000 条记录；本机按整部作品合并去重，再拆成最多 20 部/2000 章的批次。</li><li>同一批最多 4 路并行提交；单部作品不会被拆散，避免部分成功造成错误章均值。</li><li>每部作品必须包含完整 V 章节集合；缺章、非 V 章或未知作品会整部拒绝。</li><li>点击只接受非负整数；缺失不补零，导入后才计算 V 章均点击及留存代理。</li><li>任务报告只包含任务状态、作品 ID、数量和错误代码，不导出章节点击值。</li></ul></div></details>
    </section>
  );
}
