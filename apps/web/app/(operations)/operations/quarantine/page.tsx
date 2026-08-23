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
import type { EntityType, QuarantineStatus, QuarantineSummaryPage } from "../../../../types/api";

export const dynamic = "force-dynamic";
const ENTITY_TYPES = ["work", "author", "tag_page", "search_page"] as const;
const STATUSES = ["open", "resolved", "ignored"] as const;

export default async function QuarantinePage({ searchParams }: { searchParams: Promise<RawSearchParams> }) {
  const raw = await searchParams;
  const entityType = allowedSearchValue<EntityType>(raw.entity_type, ENTITY_TYPES);
  const status = allowedSearchValue<QuarantineStatus>(raw.status, STATUSES);
  const cursor = firstSearchValue(raw.cursor, 1_024);
  const query = new URLSearchParams({ limit: "30" });
  if (entityType) query.set("entity_type", entityType);
  if (status) query.set("status", status);
  if (cursor) query.set("cursor", cursor);
  let page: QuarantineSummaryPage | null = null;
  try {
    page = await fetchApi<QuarantineSummaryPage>(`/api/v1/operations/quarantine?${query}`);
  } catch {
    // Render fixed private-service failure state below.
  }
  const nextHref = page?.next_cursor
    ? pageHref("/operations/quarantine", {
        entity_type: entityType,
        status,
        cursor: page.next_cursor,
      })
    : null;

  return (
    <main className="catalog-page">
      <header className="page-heading"><div><p className="eyebrow">Quarantine review</p><h1>隔离队列</h1></div><p>仅显示固定错误码；来源标识、自由文本和尝试关联不会暴露。</p></header>
      <form className="filter-bar operations-filter" action="/operations/quarantine" method="get">
        <label>实体类型<select name="entity_type" defaultValue={entityType ?? ""}><option value="">全部</option>{ENTITY_TYPES.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>状态<select name="status" defaultValue={status ?? ""}><option value="">全部</option>{STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>
        <button type="submit">筛选</button><Link className="clear-filter" href="/operations/quarantine">清除</Link>
      </form>
      {page ? <>
        <div className="table-wrap" role="region" aria-label="隔离记录表格，可横向滚动" tabIndex={0}><table className="operations-table"><caption className="sr-only">隔离记录列表</caption>
          <thead><tr><th>记录</th><th>实体</th><th>状态</th><th>错误码</th><th>首次 / 最近失败</th></tr></thead>
          <tbody>{page.items.map((item) => <tr key={item.id}>
            <td>#{item.id}</td><td>{item.entity_type}</td><td><span className={`status-pill status-${item.status}`}>{item.status}</span></td>
            <td><code>{item.error_code}</code></td><td><time dateTime={item.first_failed_at}>{formatDateTime(item.first_failed_at)}</time><small>{formatDateTime(item.last_failed_at)}</small></td>
          </tr>)}</tbody>
        </table></div>
        {page.items.length === 0 ? <p className="empty-state">隔离队列为空。</p> : null}
        <div className="pagination"><NextPageLink href={nextHref} /></div>
      </> : <section className="state-panel"><p>隔离队列 API 暂不可用。</p></section>}
    </main>
  );
}
