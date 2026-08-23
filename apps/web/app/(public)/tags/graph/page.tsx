import Link from "next/link";

import { TagAssociationChart } from "../../../../components/charts/tag-association-chart";
import { StatCard } from "../../../../components/ui/stat-card";
import { fetchApi } from "../../../../lib/api/client";
import {
  boundedIntegerSearchValue,
  firstSearchValue,
  type RawSearchParams,
} from "../../../../lib/url/search";
import type { TagAssociationGraphResponse } from "../../../../types/api";

export const dynamic = "force-dynamic";

function percent(basisPoints: number): string {
  return `${(basisPoints / 100).toFixed(2)}%`;
}

export default async function TagGraphPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const raw = await searchParams;
  const anchor = firstSearchValue(raw.anchor_tag, 255);
  const minimum = boundedIntegerSearchValue(raw.minimum_cooccurrence, 1, 5_000, 1);
  const limit = boundedIntegerSearchValue(raw.limit, 1, 200, 100);
  const sampleLimit = boundedIntegerSearchValue(raw.sample_work_limit, 1, 5_000, 1_000);
  const query = new URLSearchParams({
    minimum_cooccurrence: String(minimum),
    limit: String(limit),
    sample_work_limit: String(sampleLimit),
  });
  if (anchor) query.set("anchor_tag", anchor);

  let graph: TagAssociationGraphResponse | null = null;
  try {
    graph = await fetchApi<TagAssociationGraphResponse>(
      `/api/v1/analytics/tags/co-occurrence?${query}`,
    );
  } catch {
    // Fixed private-service failure state below; never use an external fallback.
  }

  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Tag associations</p><h1>标签关系图</h1></div>
        <p>仅显示样本内统计关联，不推断标签是否属于百合或任何语义类别。</p>
      </header>

      <form className="tag-graph-filter" method="get" aria-label="标签关系筛选">
        <label>锚点标签<input name="anchor_tag" defaultValue={anchor ?? ""} maxLength={255} /></label>
        <label>最小共现<input name="minimum_cooccurrence" type="number" min="1" max="5000" defaultValue={minimum} /></label>
        <label>关系上限<input name="limit" type="number" min="1" max="200" defaultValue={limit} /></label>
        <label>作品样本上限<input name="sample_work_limit" type="number" min="1" max="5000" defaultValue={sampleLimit} /></label>
        <button type="submit">应用筛选</button>
        <Link className="muted-link" href="/tags/review">查看敏感性审查</Link>
        <Link className="muted-link" href="/tags">返回标签索引</Link>
      </form>

      {graph ? (
        <>
          <p className="association-notice" role="note">
            描述性关联 · 未执行语义分类
            {graph.sample_truncated ? " · 作品样本已截断" : " · 已覆盖当前目录作品"}
            {graph.result_truncated ? " · 关系结果已截断" : ""}
          </p>
          <section className="stat-grid" aria-label="标签关系样本摘要">
            <StatCard label="目录作品" value={String(graph.catalog_work_count)} note="当前规范化目录" />
            <StatCard label="样本作品" value={String(graph.sampled_work_count)} note={`上限 ${sampleLimit}`} />
            <StatCard label="样本标签" value={String(graph.observed_tag_count)} note="去重公开标签" />
            <StatCard label="合格关系" value={String(graph.eligible_edge_count)} note={`返回 ${graph.edges.length}`} />
          </section>
          <section className="chart-panel" aria-labelledby="tag-graph-heading">
            <div className="section-heading">
              <div><p className="eyebrow">Association graph</p><h2 id="tag-graph-heading">共现网络</h2></div>
              <p>节点大小表示样本作品数；连线粗细表示共现作品数。</p>
            </div>
            <TagAssociationChart edges={graph.edges} />
          </section>
          <section className="detail-panel tag-edge-table" aria-labelledby="tag-table-heading">
            <div className="section-heading">
              <div><p className="eyebrow">Accessible evidence</p><h2 id="tag-table-heading">关系明细</h2></div>
              <p>表格是图形的完整键盘与屏幕阅读器替代视图。</p>
            </div>
            {graph.edges.length ? (
              <div className="table-wrap" tabIndex={0}>
                <table className="operations-table">
                  <thead><tr><th>标签 A</th><th>标签 B</th><th>共现作品</th><th>样本支持度</th><th>Jaccard</th><th>PMI</th></tr></thead>
                  <tbody>{graph.edges.map((edge) => (
                    <tr key={`${edge.left.tag_name}\u0000${edge.right.tag_name}`}>
                      <td><Link href={`/tags/${encodeURIComponent(edge.left.tag_name)}`}>#{edge.left.tag_name}</Link><small>{edge.left.sampled_work_count} 件样本作品</small></td>
                      <td><Link href={`/tags/${encodeURIComponent(edge.right.tag_name)}`}>#{edge.right.tag_name}</Link><small>{edge.right.sampled_work_count} 件样本作品</small></td>
                      <td>{edge.cooccurrence_work_count}</td>
                      <td>{percent(edge.sample_support_basis_points)}</td>
                      <td>{percent(edge.jaccard_basis_points)}</td>
                      <td>{(edge.pmi_milli_bits / 1000).toFixed(3)} bit</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <p className="directory-empty">当前条件没有合格关系；可降低最小共现或清除锚点。</p>}
          </section>
        </>
      ) : (
        <section className="state-panel"><p>标签关系 API 暂不可用，未改用任何外部数据源。</p></section>
      )}
    </main>
  );
}
