import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchApi } from "../../../../lib/api/client";
import { formatCount } from "../../../../lib/format/number";
import { safeRouteSegment } from "../../../../lib/url/search";
import type { JjwxcNovel } from "../../../../types/api";

export const dynamic = "force-dynamic";

export default async function NovelDetailPage({
  params,
}: {
  params: Promise<{ novelId: string }>;
}) {
  const novelId = safeRouteSegment((await params).novelId, 12);
  if (!novelId || !/^\d+$/u.test(novelId)) notFound();
  let novel: JjwxcNovel;
  try {
    novel = await fetchApi<JjwxcNovel>(`/api/v1/jjwxc/novels/${novelId}`);
  } catch {
    notFound();
  }
  const chapterCount = novel.non_v_chapter_count + novel.v_chapter_count;
  const clickCoveragePercent = chapterCount
    ? (novel.chapter_click_coverage_count * 100) / chapterCount
    : null;
  const retentionPercent =
    novel.v_to_non_v_click_retention_basis_points === null
      ? null
      : novel.v_to_non_v_click_retention_basis_points / 100;
  return (
    <main className="catalog-page">
      <Link className="muted-link" href="/novels">
        ← 返回小说分析
      </Link>
      <header className="page-heading detail-heading">
        <div>
          <p className="eyebrow">Novel snapshot · {novel.novel_id}</p>
          <h1>{novel.title}</h1>
        </div>
        <p>{novel.novel_type}</p>
      </header>
      <section className="detail-grid">
        <article className="detail-panel">
          <div className="panel-heading">
            <h2>公开聚合元数据</h2>
            <span>{novel.status}</span>
          </div>
          <dl className="detail-list">
            <div>
              <dt>作者</dt>
              <dd>
                <Link href={`/authors/${novel.author_id}`}>
                  {novel.author_display_name}
                </Link>
              </dd>
            </div>
            <div>
              <dt>字数</dt>
              <dd>{formatCount(novel.word_count)}</dd>
            </div>
            <div>
              <dt>总书评数</dt>
              <dd>{formatCount(novel.review_count)}</dd>
            </div>
            <div>
              <dt>收藏数</dt>
              <dd>{formatCount(novel.favorite_count)}</dd>
            </div>
            <div>
              <dt>作品积分</dt>
              <dd>{formatCount(novel.points)}</dd>
            </div>
            <div>
              <dt>非 V 章节章均点击数</dt>
              <dd>
                {novel.average_non_v_chapter_click_count === null
                  ? "未公开"
                  : formatCount(novel.average_non_v_chapter_click_count)}
              </dd>
            </div>
            <div>
              <dt>V 章节章均点击数</dt>
              <dd>
                {novel.average_v_chapter_click_count === null
                  ? "当前采集响应不可见"
                  : formatCount(novel.average_v_chapter_click_count)}
              </dd>
            </div>
            <div>
              <dt>V/非 V 点击留存比（代理）</dt>
              <dd>
                {retentionPercent === null
                  ? "缺少 V/非 V 共同可见点击"
                  : `${retentionPercent.toFixed(1)}%`}
              </dd>
            </div>
            <div>
              <dt>可见点击章节覆盖</dt>
              <dd>
                {novel.chapter_click_coverage_count}/{chapterCount || "—"}
                {clickCoveragePercent === null
                  ? ""
                  : `（${clickCoveragePercent.toFixed(1)}%）`}
              </dd>
            </div>
            <div>
              <dt>作品视角</dt>
              <dd>{novel.perspective ?? "未观测"}</dd>
            </div>
          </dl>
        </article>
        <aside className="state-panel">
          <div className="panel-heading">
            <h2>解释边界</h2>
            <span>METADATA</span>
          </div>
          <p>
            本页不含文案原文、章节标题、章节正文、评论内容或读者身份；仅可保留文案长度、句数和固定主题词等不可还原特征。指标是某一时点的快照，不代表平台背书或作品质量结论。
          </p>
          <p>
            点击覆盖率 = 有非空点击数的章节数 ÷ 已解析章节总数。V
            章点击不可见时，V 章仍计入分母、但不进入分子，因此总覆盖率会降低；缺失值不会补零，也不会改变非 V 章均点击。
          </p>
          <p>
            “V/非 V 点击留存比” = V 章节章均点击数 ÷ 非 V
            章节章均点击数，仅在两者同时可见且非 V 均值大于 0
            时计算。它是点击量比值代理，并非去重读者的真实留存率，也不限制在 100% 以内。
          </p>
          {novel.synopsis_char_count !== null ? (
            <p>
              文案画像：{novel.synopsis_char_count} 字、
              {novel.synopsis_sentence_count ?? "—"} 句
              {novel.synopsis_theme_terms.length
                ? `，主题词 ${novel.synopsis_theme_terms.join(" / ")}`
                : "，暂无主题词命中"}
              。
            </p>
          ) : null}
          <div className="tag-row">
            {novel.tags.map((tag) => (
              <span key={tag}>#{tag}</span>
            ))}
          </div>
        </aside>
      </section>
    </main>
  );
}
