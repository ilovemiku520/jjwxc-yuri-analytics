import Link from "next/link";

import { CohortFileImporter } from "../../../components/jjwxc/cohort-file-importer";
import { MultivariateExplorer } from "../../../components/jjwxc/multivariate-explorer";
import { RatingExplorer } from "../../../components/jjwxc/rating-explorer";
import { fetchApi } from "../../../lib/api/client";
import type {
  JjwxcMultivariateResponse,
  JjwxcRatingResponse,
  JjwxcSearchResponse,
} from "../../../types/api";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  novels?: string | string[];
  q?: string | string[];
}>;

function firstValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function selectedNovelIds(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((item) => item.trim())
        .filter((item) => /^[1-9][0-9]{0,11}$/u.test(item)),
    ),
  ).slice(0, 100);
}

function analyticsHref(ids: string[], query: string): string {
  const parameters = new URLSearchParams();
  if (ids.length) parameters.set("novels", ids.join(","));
  if (query) parameters.set("q", query);
  const suffix = parameters.toString();
  return suffix ? `/analytics?${suffix}` : "/analytics";
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const parameters = await searchParams;
  const ids = selectedNovelIds(firstValue(parameters.novels));
  const query = firstValue(parameters.q).trim().slice(0, 80);
  let data: JjwxcMultivariateResponse | null = null;
  let ratings: JjwxcRatingResponse | null = null;
  let search: JjwxcSearchResponse | null = null;
  const cohortPath = ids.length
    ? `/api/v1/jjwxc/analytics/multivariate?novel_ids=${ids.join(",")}`
    : "/api/v1/jjwxc/analytics/multivariate";
  const [dataResult, ratingResult, searchResult] = await Promise.allSettled([
    fetchApi<JjwxcMultivariateResponse>(cohortPath),
    fetchApi<JjwxcRatingResponse>("/api/v1/jjwxc/analytics/ratings"),
    query
      ? fetchApi<JjwxcSearchResponse>(
          `/api/v1/jjwxc/search?query=${encodeURIComponent(query)}&limit=20&offset=0`,
        )
      : Promise.resolve(null),
  ]);
  data = dataResult.status === "fulfilled" ? dataResult.value : null;
  ratings = ratingResult.status === "fulfilled" ? ratingResult.value : null;
  search = searchResult.status === "fulfilled" ? searchResult.value : null;

  return (
    <main className="dashboard">
      <section className="page-heading analysis-heading">
        <div>
          <p className="eyebrow">JJWXC SNAPSHOT ANALYTICS</p>
          <h1>
            时间与变量
            <br />
            <em>交互分析</em>
          </h1>
        </div>
        <div>
          <p>
            同一时间轴最多并列三个指标；相关矩阵使用 log(1+x) 与标准化后的
            Pearson 相关系数，可调样本比较同时报告 Pearson、Spearman
            与置信区间。
          </p>
          <p>
            历史仅指项目自行保存的每日快照，不代表平台提供的历史。
            {data?.data_mode === "database_snapshot"
              ? " 当前为数据库快照。"
              : " 当前为合成 Fixture 演示。"}
          </p>
        </div>
      </section>

      {data ? (
        <>
          <section
            className="chart-panel cohort-builder"
            aria-labelledby="cohort-builder-title"
          >
            <div className="panel-heading">
              <div>
                <p className="eyebrow">CUSTOM ANALYTICS INDEX · MAX 100</p>
                <h2 id="cohort-builder-title">自定义作品统计集合</h2>
              </div>
              <span>
                {ids.length
                  ? `已选择 ${ids.length} 部作品`
                  : "默认统计全部详细快照"}
              </span>
            </div>
            <form
              action="/analytics"
              className="cohort-search"
              method="get"
              role="search"
            >
              {ids.length ? (
                <input name="novels" type="hidden" value={ids.join(",")} />
              ) : null}
              <label htmlFor="cohort-query">搜索作品名或作者名后加入统计</label>
              <div>
                <input
                  defaultValue={query}
                  id="cohort-query"
                  maxLength={80}
                  name="q"
                  placeholder="例如：台风 / 玄笺"
                  type="search"
                />
                <button type="submit">搜索可统计作品</button>
              </div>
            </form>
            <CohortFileImporter />
            {ids.length ? (
              <div className="cohort-selection" aria-label="已选择作品">
                {ids.map((novelId) => {
                  const novel = data?.cohort_items.find(
                    (item) => item.novel_id === novelId,
                  );
                  return (
                    <Link
                      href={analyticsHref(
                        ids.filter((item) => item !== novelId),
                        query,
                      )}
                      key={novelId}
                    >
                      {novel?.title ?? `JJWXC ${novelId}`} <span>移除</span>
                    </Link>
                  );
                })}
                <Link className="cohort-clear" href={analyticsHref([], query)}>
                  清空自定义集合
                </Link>
              </div>
            ) : (
              <p className="analysis-note">
                未添加作品时使用当前全部详细快照，但不会在页面列出全部作品。
              </p>
            )}
            {query ? (
              <div className="cohort-search-results" aria-live="polite">
                <p>找到 {search?.total ?? 0} 部可用于详细统计的作品</p>
                {search?.items.map((item) => {
                  const included = ids.includes(item.novel_id);
                  const nextIds = included
                    ? ids
                    : [...ids, item.novel_id].slice(0, 100);
                  return (
                    <article key={item.novel_id}>
                      <div>
                        <strong>{item.title}</strong>
                        <span>{item.author_display_name}</span>
                      </div>
                      {included ? (
                        <span>已加入</span>
                      ) : ids.length >= 100 ? (
                        <span>已达 100 部上限</span>
                      ) : (
                        <Link href={analyticsHref(nextIds, query)}>
                          加入统计
                        </Link>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : null}
          </section>
          {ratings ? <RatingExplorer data={ratings} /> : null}
          <MultivariateExplorer data={data} />
        </>
      ) : (
        <section className="state-panel" aria-live="polite">
          <div className="panel-heading">
            <h2>分析数据服务暂不可用</h2>
            <span>SAFE FALLBACK</span>
          </div>
          <p>数据服务恢复后刷新页面；前端不会直接向晋江文学城发起请求。</p>
        </section>
      )}
    </main>
  );
}
