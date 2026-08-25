import Link from "next/link";

import { fetchApi } from "../../../lib/api/client";
import { formatCount } from "../../../lib/format/number";
import {
  allowedSearchValue,
  pageHref,
  type RawSearchParams,
} from "../../../lib/url/search";
import type { JjwxcAuthorPage, JjwxcAuthorSort } from "../../../types/api";

export const dynamic = "force-dynamic";
const sorts = ["favorites", "reviews", "points", "novels", "rankings"] as const;
const labels: Record<JjwxcAuthorSort, string> = {
  favorites: "总收藏",
  reviews: "总书评",
  points: "总积分",
  novels: "作品数",
  rankings: "双榜上榜次数",
};

export default async function AuthorsPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const sort =
    allowedSearchValue((await searchParams).sort, sorts) ?? "favorites";
  let page: JjwxcAuthorPage | null = null;
  try {
    page = await fetchApi<JjwxcAuthorPage>(
      `/api/v1/jjwxc/authors?sort=${sort}`,
    );
  } catch {}
  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Author analytics</p>
          <h1>作者数据</h1>
        </div>
        <p>
          按公开作品的聚合计数观察作者样本，不分析简介、社交账号或读者身份。
        </p>
      </header>
      <nav className="ranking-tabs" aria-label="作者排序">
        {sorts.map((item) => (
          <Link
            aria-current={item === sort ? "page" : undefined}
            className="ranking-tab"
            href={pageHref("/authors", { sort: item })}
            key={item}
          >
            {labels[item]}
          </Link>
        ))}
      </nav>
      {page ? (
        <section className="directory-list" aria-label="JJWXC 作者列表">
          {page.items.map((author, index) => {
            const score =
              sort === "favorites"
                ? author.total_favorite_count
                : sort === "reviews"
                  ? author.total_review_count
                  : sort === "points"
                    ? author.total_points
                    : sort === "rankings"
                      ? author.ranking_appearance_count
                      : author.novel_count;
            const workCount =
              author.profile_nonlocked_work_count ?? author.novel_count;
            return (
              <Link
                className="directory-row ranking-row"
                href={`/authors/${author.author_id}`}
                key={author.author_id}
              >
                <span>
                  <strong>
                    {index + 1}. {author.author_display_name}
                  </strong>
                  <small>authorid {author.author_id}</small>
                </span>
                <span>{formatCount(workCount)} 部非锁定作品</span>
                <span>
                  {formatCount(score)} {labels[sort]}
                </span>
              </Link>
            );
          })}
        </section>
      ) : (
        <section className="state-panel">
          <p>作者分析 API 暂不可用。</p>
        </section>
      )}
    </main>
  );
}
