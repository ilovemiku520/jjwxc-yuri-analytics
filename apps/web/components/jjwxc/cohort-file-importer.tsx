"use client";

import { useMemo, useState } from "react";

import {
  MAX_COHORT_FILE_BYTES,
  MIN_CORRELATION_SAMPLE_SIZE,
  parseCohortFile,
  type ParsedCohortFile,
  type RejectedCohortRow,
} from "../../lib/jjwxc/cohort-file";
import type {
  JjwxcCohortImportItem,
  JjwxcCohortImportResponse,
} from "../../types/api";

const parseErrorLabels: Record<RejectedCohortRow["reason"], string> = {
  missing_novel_id: "novel_id 为空",
  invalid_novel_id: "必须是 1–12 位正整数字符串",
  duplicate_novel_id: "重复 ID",
  limit_exceeded: "超过单次 100 部上限",
};

const fileErrorLabels: Record<string, string> = {
  cohort_file_empty: "文件为空。",
  cohort_file_header_missing: "首行必须包含名为 novel_id 的列。",
  cohort_file_no_data_rows: "表头下没有数据行。",
  cohort_file_unclosed_quote: "CSV 中存在未闭合的引号。",
};

const collectionStatusLabels: Record<JjwxcCohortImportItem["status"], string> =
  {
    ready: "已采集，可分析",
    queued: "等待定向采集",
    running: "正在采集",
    failed: "采集失败，已排除",
    not_queued: "尚未排队，已排除",
  };

function failureCsv(
  parsed: ParsedCohortFile,
  items: JjwxcCohortImportItem[],
): string {
  const lines = ["row_number,novel_id,status,error_code"];
  for (const row of parsed.rejectedRows) {
    lines.push(
      `${row.rowNumber},"${row.value.replaceAll('"', '""')}",rejected,${row.reason}`,
    );
  }
  for (const item of items.filter(
    (candidate) =>
      candidate.status === "failed" || candidate.status === "not_queued",
  )) {
    lines.push(
      `,${item.novel_id},${item.status},${item.error_code ?? "not_queued"}`,
    );
  }
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}

export function CohortFileImporter() {
  const [parsed, setParsed] = useState<ParsedCohortFile | null>(null);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [response, setResponse] = useState<JjwxcCohortImportResponse | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const readyIds =
    response?.items
      .filter((item) => item.status === "ready")
      .map((item) => item.novel_id) ?? [];
  const failedItems =
    response?.items.filter(
      (item) => item.status === "failed" || item.status === "not_queued",
    ) ?? [];
  const failureCount = (parsed?.rejectedRows.length ?? 0) + failedItems.length;
  const analysisHref = readyIds.length
    ? `/analytics?novels=${encodeURIComponent(readyIds.join(","))}`
    : "";
  const statusCounts = useMemo(
    () =>
      Object.fromEntries(
        (["ready", "queued", "running", "failed", "not_queued"] as const).map(
          (status) => [
            status,
            response?.items.filter((item) => item.status === status).length ??
              0,
          ],
        ),
      ),
    [response],
  );

  async function selectFile(file: File | undefined) {
    setParsed(null);
    setResponse(null);
    setError("");
    setFileName(file?.name ?? "");
    if (!file) return;
    if (!/\.(csv|tsv|txt)$/iu.test(file.name)) {
      setError("仅支持 UTF-8 编码的 .csv、.tsv 或 .txt 文件。");
      return;
    }
    if (file.size > MAX_COHORT_FILE_BYTES) {
      setError("文件不能超过 256 KiB。");
      return;
    }
    try {
      setParsed(parseCohortFile(await file.text(), file.name));
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      setError(fileErrorLabels[code] ?? "无法解析该表格，请检查编码和分隔符。");
    }
  }

  async function submit(mode: "queue" | "status") {
    if (!parsed?.validIds.length) return;
    setBusy(true);
    setError("");
    try {
      const result = await fetch("/api/jjwxc/cohorts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, novel_ids: parsed.validIds }),
      });
      if (!result.ok) throw new Error("cohort_service_error");
      setResponse((await result.json()) as JjwxcCohortImportResponse);
    } catch {
      setError("定向采集服务暂不可用，文件仍保留在本机浏览器内，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  function downloadFailureReport() {
    if (!parsed || failureCount === 0) return;
    const url = URL.createObjectURL(
      new Blob([failureCsv(parsed, response?.items ?? [])], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `jjwxc-cohort-failures-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="cohort-file-importer">
      <div className="cohort-file-controls">
        <label>
          <span>导入作品 ID 表</span>
          <input
            accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain"
            onChange={(event) => void selectFile(event.target.files?.[0])}
            type="file"
          />
        </label>
        <button
          disabled={busy || !parsed?.validIds.length}
          onClick={() => void submit("queue")}
          type="button"
        >
          {busy ? "正在提交…" : "校验并排队采集"}
        </button>
        <button
          disabled={busy || !response || !parsed?.validIds.length}
          onClick={() => void submit("status")}
          type="button"
        >
          刷新采集状态
        </button>
      </div>
      <details className="statistics-details cohort-file-requirements">
        <summary>输入数据类型与排除规则</summary>
        <div>
          <ul>
            <li>
              仅接收 UTF-8 CSV、TSV、TXT，最大 256 KiB、100 个唯一作品 ID。
            </li>
            <li>
              首行必须含 novel_id；值必须是 1–12
              位正整数字符串，禁止小数、科学计数法和公式。
            </li>
            <li>
              空值、非法值、重复项、超限项会在本机解析阶段排除，不会发送至服务端。
            </li>
            <li>
              服务端仅将成功入库且属于百合范围的作品加入分析；采集失败项不会补零。
            </li>
            <li>
              相关分析要求每一对变量至少有 {MIN_CORRELATION_SAMPLE_SIZE}{" "}
              个共同有效样本。
            </li>
          </ul>
        </div>
      </details>
      {error ? (
        <p className="cohort-import-error" role="alert">
          {error}
        </p>
      ) : null}
      {parsed ? (
        <div className="cohort-import-summary" aria-live="polite">
          <p>
            {fileName}：读取 {parsed.dataRowCount} 行，合法唯一 ID{" "}
            {parsed.validIds.length} 个， 本机排除 {parsed.rejectedRows.length}{" "}
            行。
          </p>
          {response ? (
            <p>
              已采集 {statusCounts.ready} · 排队 {statusCounts.queued} · 采集中{" "}
              {statusCounts.running} · 采集失败/未排队{" "}
              {statusCounts.failed + statusCounts.not_queued}
            </p>
          ) : null}
          {readyIds.length && readyIds.length < MIN_CORRELATION_SAMPLE_SIZE ? (
            <p className="cohort-sample-warning">
              当前仅 {readyIds.length} 个可分析作品，尚未达到 30
              个成对有效样本的最低筛选门槛。
            </p>
          ) : null}
          <div className="cohort-import-actions">
            {analysisHref ? (
              <a href={analysisHref}>用 {readyIds.length} 部成功作品进行比较</a>
            ) : null}
            <button
              disabled={!failureCount}
              onClick={downloadFailureReport}
              type="button"
            >
              下载排除/失败清单（{failureCount}）
            </button>
          </div>
        </div>
      ) : null}
      {parsed && (parsed.rejectedRows.length || failedItems.length) ? (
        <div className="cohort-import-report">
          <table>
            <thead>
              <tr>
                <th>表格行</th>
                <th>作品 ID</th>
                <th>处理结果</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              {parsed.rejectedRows.map((row) => (
                <tr key={`${row.rowNumber}-${row.reason}`}>
                  <td>{row.rowNumber}</td>
                  <td>{row.value || "—"}</td>
                  <td>本机排除</td>
                  <td>{parseErrorLabels[row.reason]}</td>
                </tr>
              ))}
              {failedItems.map((item) => (
                <tr key={item.novel_id}>
                  <td>—</td>
                  <td>{item.novel_id}</td>
                  <td>{collectionStatusLabels[item.status]}</td>
                  <td>{item.error_code ?? "not_queued"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
