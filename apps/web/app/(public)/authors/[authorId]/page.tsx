import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchApi } from "../../../../lib/api/client";
import { formatCount } from "../../../../lib/format/number";
import { safeRouteSegment } from "../../../../lib/url/search";
import type { JjwxcAuthorDetail } from "../../../../types/api";

export const dynamic = "force-dynamic";

export default async function AuthorDetailPage({
  params,
}: {
  params: Promise<{ authorId: string }>;
}) {
  const authorId = safeRouteSegment((await params).authorId, 12);
  if (!authorId || !/^\d+$/u.test(authorId)) notFound();
  let detail: JjwxcAuthorDetail;
  try {
    detail = await fetchApi<JjwxcAuthorDetail>(
      `/api/v1/jjwxc/authors/${authorId}`,
    );
  } catch {
    notFound();
  }
  const { author } = detail;
  return (
    <main className="catalog-page">
      <Link className="muted-link" href="/authors">
        ← 返回作者数据
      </Link>
      <header className="page-heading detail-heading">
        <div>
          <p className="eyebrow">JJWXC authorid {author.author_id}</p>
          <h1>{author.author_display_name}</h1>
        </div>
        <p>
          {formatCount(author.novel_count)} 部已统计百合小说 ·{" "}
          {author.profile_locked_work_count ?? "—"} 部锁定作品已排除
          {author.profile_observed_at
            ? ` · 专栏快照 ${author.profile_observed_at.slice(0, 10)}`
            : " · 专栏将在下一次定时任务优先补全"}
        </p>
      </header>
      <section className="stat-grid author-stat-grid">
        <Stat
          label="非锁定作品"
          value={author.profile_nonlocked_work_count}
          source="作者专栏"
        />
        <Stat
          label="作者收藏"
          value={author.profile_author_favorite_count}
          source="作者专栏"
        />
        <Stat
          label="作品总收藏"
          value={author.total_favorite_count}
          source="已统计作品"
        />
        <Stat
          label="写文总字数"
          value={author.profile_total_word_count}
          source="非锁定作品"
        />
        <Stat
          label="总积分"
          value={author.profile_total_points}
          source="非锁定作品"
        />
        <Stat
          label="双榜上榜次数"
          value={author.ranking_appearance_count}
          source={`${author.ranking_observed_day_count} 个观测日`}
        />
      </section>
      <section className="novel-grid author-novel-grid">
        {detail.novels.map((novel) => (
          <article className="novel-card" key={novel.novel_id}>
            <span className="boundary-badge">{novel.status}</span>
            <h2>
              <Link href={`/novels/${novel.novel_id}`}>{novel.title}</Link>
            </h2>
            <p>{novel.novel_type}</p>
            <dl className="metric-strip">
              <div>
                <dt>收藏</dt>
                <dd>{formatCount(novel.favorite_count)}</dd>
              </div>
              <div>
                <dt>书评</dt>
                <dd>{formatCount(novel.review_count)}</dd>
              </div>
              <div>
                <dt>字数</dt>
                <dd>{formatCount(novel.word_count)}</dd>
              </div>
            </dl>
          </article>
        ))}
      </section>
    </main>
  );
}

function Stat({
  label,
  value,
  source,
}: {
  label: string;
  value: number | null;
  source: string;
}) {
  return (
    <article className="stat-card">
      <p className="stat-label">{label}</p>
      <p className="stat-value">
        {value === null ? "等待定时补全" : formatCount(value)}
      </p>
      <p className="stat-note">{source} · 公开聚合快照</p>
    </article>
  );
}
