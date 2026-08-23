import Link from "next/link";

import { NextPageLink } from "../../../../components/ui/next-page-link";
import { fetchApi } from "../../../../lib/api/client";
import { formatDateTime } from "../../../../lib/format/number";
import {
  allowedSearchValue,
  firstSearchValue,
  pageHref,
  type RawSearchParams,
} from "../../../../lib/url/search";
import type { OperationalTaskPage, TaskStatus } from "../../../../types/api";

export const dynamic = "force-dynamic";
const STATUSES = ["pending", "running", "succeeded", "failed", "cancelled"] as const;

export default async function TasksPage({ searchParams }: { searchParams: Promise<RawSearchParams> }) {
  const raw = await searchParams;
  const status = allowedSearchValue<TaskStatus>(raw.status, STATUSES);
  const rawRunId = firstSearchValue(raw.run_id, 20);
  const runId = rawRunId && /^[1-9]\d*$/u.test(rawRunId) ? rawRunId : undefined;
  const cursor = firstSearchValue(raw.cursor, 1_024);
  const query = new URLSearchParams({ limit: "30" });
  if (status) query.set("status", status);
  if (runId) query.set("run_id", runId);
  if (cursor) query.set("cursor", cursor);
  let page: OperationalTaskPage | null = null;
  try {
    page = await fetchApi<OperationalTaskPage>(`/api/v1/operations/tasks?${query}`);
  } catch {
    // Render fixed private-service failure state below.
  }
  const nextHref = page?.next_cursor
    ? pageHref("/operations/tasks", { run_id: runId, status, cursor: page.next_cursor })
    : null;

  return (
    <main className="catalog-page">
      <header className="page-heading"><div><p className="eyebrow">Task ledger</p><h1>任务状态</h1></div><p>逻辑目标、幂等键、租约和工作进程标识均被排除。</p></header>
      <form className="filter-bar operations-filter" action="/operations/tasks" method="get">
        <label>运行 ID<input name="run_id" inputMode="numeric" pattern="[1-9][0-9]*" defaultValue={runId} /></label>
        <label>状态<select name="status" defaultValue={status ?? ""}><option value="">全部</option>{STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>
        <button type="submit">筛选</button><Link className="clear-filter" href="/operations/tasks">清除</Link>
      </form>
      {page ? <>
        <div className="table-wrap" role="region" aria-label="任务表格，可横向滚动" tabIndex={0}><table className="operations-table"><caption className="sr-only">任务列表</caption>
          <thead><tr><th>任务</th><th>运行</th><th>状态</th><th>尝试</th><th>错误码</th><th>更新时间</th></tr></thead>
          <tbody>{page.items.map((item) => <tr key={item.id}>
            <td><strong>#{item.id}</strong><small>{item.task_type}</small></td><td>#{item.run_id}</td>
            <td><span className={`status-pill status-${item.status}`}>{item.status}</span></td><td>{item.attempt_count}</td>
            <td><code>{item.last_error_code ?? "—"}</code></td><td><time dateTime={item.updated_at}>{formatDateTime(item.updated_at)}</time></td>
          </tr>)}</tbody>
        </table></div>
        {page.items.length === 0 ? <p className="empty-state">没有匹配的任务。</p> : null}
        <div className="pagination"><NextPageLink href={nextHref} /></div>
      </> : <section className="state-panel"><p>任务 API 暂不可用。</p></section>}
    </main>
  );
}
