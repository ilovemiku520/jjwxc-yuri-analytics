import Link from "next/link";

import { TagSensitivityChart } from "../../../../components/charts/tag-sensitivity-chart";
import { StatCard } from "../../../../components/ui/stat-card";
import { fetchApi } from "../../../../lib/api/client";
import {
  boundedIntegerSearchValue,
  firstSearchValue,
  type RawSearchParams,
} from "../../../../lib/url/search";
import type { TagAssociationSensitivityResponse } from "../../../../types/api";

export const dynamic = "force-dynamic";

function percent(basisPoints: number): string {
  return `${(basisPoints / 100).toFixed(2)}%`;
}

export default async function TagReviewPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const raw = await searchParams;
  const anchor = firstSearchValue(raw.anchor_tag, 255);
  const candidateLimit = boundedIntegerSearchValue(raw.candidate_limit, 1, 200, 50);
  const sampleLimit = boundedIntegerSearchValue(raw.sample_work_limit, 1, 5_000, 1_000);
  const query = new URLSearchParams({
    candidate_limit: String(candidateLimit),
    sample_work_limit: String(sampleLimit),
  });
  if (anchor) query.set("anchor_tag", anchor);

  let report: TagAssociationSensitivityResponse | null = null;
  try {
    report = await fetchApi<TagAssociationSensitivityResponse>(
      `/api/v1/analytics/tags/association-sensitivity?${query}`,
    );
  } catch {
    // Fixed private-service failure state below; never use an external fallback.
  }
  const comparisonLimited = report?.points.some((point) => !point.stability_comparable) ?? false;

  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Human review evidence</p><h1>标签关系审查</h1></div>
        <p>比较固定共现阈值并排列待人工复核证据；页面不会判断或保存语义类别。</p>
      </header>

      <form className="tag-review-filter" method="get" aria-label="标签审查筛选">
        <label>锚点标签<input name="anchor_tag" defaultValue={anchor ?? ""} maxLength={255} /></label>
        <label>候选上限<input name="candidate_limit" type="number" min="1" max="200" defaultValue={candidateLimit} /></label>
        <label>作品样本上限<input name="sample_work_limit" type="number" min="1" max="5000" defaultValue={sampleLimit} /></label>
        <button type="submit">应用筛选</button>
        <Link className="muted-link" href="/tags/graph">返回关系图</Link>
      </form>

      {report ? (
        <>
          <p className="association-notice" role="note">
            描述性证据 · 未执行语义分类 · 固定阈值 {report.thresholds.join(" / ")}
            {report.sample_truncated ? " · 作品样本已截断" : ""}
          </p>
          {(report.baseline_result_truncated || comparisonLimited) && (
            <p className="sensitivity-warning" role="alert">
              关系集合已达到返回上限，部分阈值稳定性不可比较；请勿据此下完整总体结论。
            </p>
          )}
          <section className="stat-grid" aria-label="标签审查样本摘要">
            <StatCard label="目录作品" value={String(report.catalog_work_count)} note="当前规范化目录" />
            <StatCard label="样本作品" value={String(report.sampled_work_count)} note={`上限 ${sampleLimit}`} />
            <StatCard label="基线关系" value={String(report.baseline_edge_count)} note="阈值 1 返回集合" />
            <StatCard label="待审候选" value={String(report.review_candidates.length)} note={`上限 ${candidateLimit}`} />
          </section>

          <section className="chart-panel" aria-labelledby="sensitivity-chart-heading">
            <div className="section-heading">
              <div><p className="eyebrow">Threshold sensitivity</p><h2 id="sensitivity-chart-heading">阈值敏感性</h2></div>
              <p>横轴为固定最小共现阈值，纵轴为合格关系数量。</p>
            </div>
            <TagSensitivityChart points={report.points} />
            <div className="table-wrap sensitivity-table" tabIndex={0}>
              <table className="operations-table">
                <thead><tr><th scope="col">最小共现</th><th scope="col">合格关系</th><th scope="col">返回关系</th><th scope="col">基线保留率</th><th scope="col">可比较</th></tr></thead>
                <tbody>{report.points.map((point) => (
                  <tr key={point.minimum_cooccurrence}>
                    <td>{point.minimum_cooccurrence}</td><td>{point.eligible_edge_count}</td>
                    <td>{point.returned_edge_count}</td><td>{percent(point.baseline_edge_retention_basis_points)}</td>
                    <td>{point.stability_comparable ? "是" : "否（已截断）"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>

          <section className="detail-panel tag-edge-table" aria-labelledby="review-candidates-heading">
            <div className="section-heading">
              <div><p className="eyebrow">Accountable review queue</p><h2 id="review-candidates-heading">待人工复核候选</h2></div>
              <p>排序仅表示统计证据强度，不代表标签分类结论。</p>
            </div>
            {report.review_candidates.length ? (
              <div className="table-wrap" tabIndex={0}>
                <table className="operations-table">
                  <thead><tr><th scope="col">序位</th><th scope="col">标签关系</th><th scope="col">共现</th><th scope="col">支持度</th><th scope="col">Jaccard</th><th scope="col">PMI</th><th scope="col">通过阈值</th><th scope="col">状态</th></tr></thead>
                  <tbody>{report.review_candidates.map((candidate) => (
                    <tr key={`${candidate.left_tag_name}\u0000${candidate.right_tag_name}`}>
                      <td>{candidate.rank}</td>
                      <td><Link href={`/tags/${encodeURIComponent(candidate.left_tag_name)}`}>#{candidate.left_tag_name}</Link><span aria-hidden="true"> ↔ </span><Link href={`/tags/${encodeURIComponent(candidate.right_tag_name)}`}>#{candidate.right_tag_name}</Link></td>
                      <td>{candidate.cooccurrence_work_count}</td><td>{percent(candidate.sample_support_basis_points)}</td>
                      <td>{percent(candidate.jaccard_basis_points)}</td><td>{(candidate.pmi_milli_bits / 1000).toFixed(3)} bit</td>
                      <td>{candidate.survives_minimum_cooccurrence.join(" / ")}</td><td>待人工复核</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <p className="directory-empty">当前条件没有待审候选；可清除锚点或提高样本上限。</p>}
          </section>
        </>
      ) : (
        <section className="state-panel"><p>标签敏感性 API 暂不可用，未改用任何外部数据源。</p></section>
      )}
    </main>
  );
}
