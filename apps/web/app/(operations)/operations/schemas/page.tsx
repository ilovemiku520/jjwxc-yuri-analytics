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
import type { EntityType, SchemaDefinitionPage, SchemaStatus } from "../../../../types/api";

export const dynamic = "force-dynamic";

const ENTITY_TYPES = ["work", "author", "tag_page", "search_page"] as const;
const STATUSES = ["discovered", "approved", "rejected"] as const;

export default async function SchemasPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const raw = await searchParams;
  const entityType = allowedSearchValue<EntityType>(raw.entity_type, ENTITY_TYPES);
  const status = allowedSearchValue<SchemaStatus>(raw.status, STATUSES);
  const cursor = firstSearchValue(raw.cursor, 1_024);
  const query = new URLSearchParams({ limit: "30" });
  if (entityType) query.set("entity_type", entityType);
  if (status) query.set("status", status);
  if (cursor) query.set("cursor", cursor);
  let page: SchemaDefinitionPage | null = null;
  try {
    page = await fetchApi<SchemaDefinitionPage>(`/api/v1/schema-definitions?${query}`);
  } catch {
    // Render fixed private-service failure state below.
  }

  const nextHref = page?.next_cursor
    ? pageHref("/operations/schemas", {
        entity_type: entityType,
        status,
        cursor: page.next_cursor,
      })
    : null;
  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Schema lifecycle</p><h1>Schema 摘要</h1></div>
        <p>结构定义本体未暴露；只显示审查状态、指纹与兼容解析器范围。</p>
      </header>
      <form className="filter-bar operations-filter" action="/operations/schemas" method="get">
        <label>实体类型<select name="entity_type" defaultValue={entityType ?? ""}><option value="">全部</option>{ENTITY_TYPES.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>状态<select name="status" defaultValue={status ?? ""}><option value="">全部</option>{STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>
        <button type="submit">筛选</button>
        <Link className="clear-filter" href="/operations/schemas">清除</Link>
      </form>
      {page ? (
        <>
          <div className="table-wrap" role="region" aria-label="Schema 表格，可横向滚动" tabIndex={0}>
            <table className="operations-table">
              <caption className="sr-only">Schema 列表</caption>
              <thead><tr><th>ID / 类型</th><th>状态</th><th>样本</th><th>指纹</th><th>最后观测</th></tr></thead>
              <tbody>{page.items.map((item) => (
                <tr key={item.id}>
                  <td><strong>#{item.id}</strong><small>{item.entity_type}</small></td>
                  <td><span className={`status-pill status-${item.status}`}>{item.status}</span></td>
                  <td>{item.sample_count}</td>
                  <td><code title={item.fingerprint}>{item.fingerprint.slice(0, 14)}…</code></td>
                  <td><time dateTime={item.last_seen_at}>{formatDateTime(item.last_seen_at)}</time></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {page.items.length === 0 ? <p className="empty-state">没有匹配的 Schema。</p> : null}
          <div className="pagination"><NextPageLink href={nextHref} /></div>
        </>
      ) : <section className="state-panel"><p>Schema API 暂不可用，未访问外部数据源。</p></section>}
    </main>
  );
}
