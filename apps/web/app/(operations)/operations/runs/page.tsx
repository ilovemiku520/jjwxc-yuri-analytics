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
import type { OperationalRunPage, RunStatus } from "../../../../types/api";

export const dynamic = "force-dynamic";
const STATUSES = ["pending", "running", "completed", "completed_with_errors", "failed", "cancelled"] as const;

export default async function RunsPage({ searchParams }: { searchParams: Promise<RawSearchParams> }) {
  const raw = await searchParams;
  const status = allowedSearchValue<RunStatus>(raw.status, STATUSES);
  const cursor = firstSearchValue(raw.cursor, 1_024);
  const query = new URLSearchParams({ limit: "30" });
  if (status) query.set("status", status);
  if (cursor) query.set("cursor", cursor);
  let page: OperationalRunPage | null = null;
  try {
    page = await fetchApi<OperationalRunPage>(`/api/v1/operations/runs?${query}`);
  } catch {
    // Render fixed private-service failure state below.
  }
  const nextHref = page?.next_cursor
    ? pageHref("/operations/runs", { status, cursor: page.next_cursor })
    : null;

  return (
    <main className="catalog-page">
      <header className="page-heading"><div><p className="eyebrow">Run ledger</p><h1>运行状态</h1></div><p>配置快照、请求者和停止详情不会进入此界面。</p></header>
      <form className="filter-bar operations-filter compact-filter" action="/operations/runs" method="get">
        <label>状态<select name="status" defaultValue={status ?? ""}><option value="">全部</option>{STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>
        <button type="submit">筛选</button><Link className="clear-filter" href="/operations/runs">清除</Link>
      </form>
      {page ? <>
        <div className="table-wrap" role="region" aria-label="运行表格，可横向滚动" tabIndex={0}><table className="operations-table"><caption className="sr-only">运行列表</caption>
          <thead><tr><th>运行</th><th>状态</th><th>任务</th><th>成功 / 失败</th><th>创建时间</th></tr></thead>
          <tbody>{page.items.map((item) => <tr key={item.id}>
            <td><strong>#{item.id} {item.run_type}</strong><small>{item.provider}</small></td>
            <td><span className={`status-pill status-${item.status}`}>{item.status}</span></td>
            <td>{item.task_count}</td><td>{item.succeeded_task_count} / {item.failed_task_count}</td>
            <td><time dateTime={item.created_at}>{formatDateTime(item.created_at)}</time></td>
          </tr>)}</tbody>
        </table></div>
        {page.items.length === 0 ? <p className="empty-state">没有匹配的运行。</p> : null}
        <div className="pagination"><NextPageLink href={nextHref} /></div>
      </> : <section className="state-panel"><p>运行 API 暂不可用。</p></section>}
    </main>
  );
}
