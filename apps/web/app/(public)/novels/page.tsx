import Link from "next/link";

import { ChannelRankings } from "../../../components/jjwxc/channel-rankings";
import { NovelExplorer } from "../../../components/jjwxc/novel-explorer";
import { fetchApi } from "../../../lib/api/client";
import type {
  JjwxcChannelRankingResponse,
  JjwxcNovelPage,
  JjwxcSearchResponse,
} from "../../../types/api";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ q?: string | string[] }>;

function firstValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

export default async function NovelsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const rawQuery = firstValue((await searchParams).q);
  const query = rawQuery.trim().slice(0, 100);
  const catalogRequest = query
    ? fetchApi<JjwxcSearchResponse>(
        `/api/v1/jjwxc/search?query=${encodeURIComponent(query)}&limit=100`,
      )
    : fetchApi<JjwxcNovelPage>(
        "/api/v1/jjwxc/novels?sort=favorites&limit=200",
      );
  const [catalogResult, goldResult, newcomerResult] = await Promise.allSettled([
    catalogRequest,
    fetchApi<JjwxcChannelRankingResponse>(
      "/api/v1/jjwxc/channel-rankings?ranking_key=channel_gold",
    ),
    fetchApi<JjwxcChannelRankingResponse>(
      "/api/v1/jjwxc/channel-rankings?ranking_key=newcomer",
    ),
  ]);
  const catalog = catalogResult.status === "fulfilled" ? catalogResult.value : null;
  const emptyRanking = (
    key: "channel_gold" | "newcomer",
    label: string,
  ): JjwxcChannelRankingResponse => ({
    ranking_key: key,
    label,
    observation_day: null,
    items: [],
  });
  const gold =
    goldResult.status === "fulfilled"
      ? goldResult.value
      : emptyRanking("channel_gold", "频道金榜");
  const newcomer =
    newcomerResult.status === "fulfilled"
      ? newcomerResult.value
      : emptyRanking("newcomer", "新手金榜");

  return (
    <main className="catalog-page novels-index-page">
      <header className="page-heading novels-heading">
        <div>
          <p className="eyebrow">Indexed yuri fiction observatory</p>
          <h1>找作品，也看见趋势</h1>
        </div>
        <p>
          标题与作者名检索直接查询后端索引；结果来自已发现的晋江百合作品快照，不会让浏览器直接请求晋江。
        </p>
      </header>

      <form action="/novels" className="catalog-search" method="get" role="search">
        <label htmlFor="catalog-query">搜索晋江百合作品</label>
        <div>
          <input
            defaultValue={query}
            id="catalog-query"
            maxLength={100}
            name="q"
            placeholder="输入作品名或作者名，例如：台风 / 鹿遇安"
            type="search"
          />
          <button type="submit">搜索索引</button>
        </div>
        <p>
          {query
            ? `“${query}”找到 ${catalog?.total ?? 0} 条结果`
            : "当前展示收藏排序；每日采集会持续扩大可搜索范围。"}
        </p>
      </form>

      <ChannelRankings channelGold={gold} newcomer={newcomer} />

      <section className="catalog-results-heading">
        <div>
          <p className="eyebrow">Searchable catalog</p>
          <h2>{query ? "搜索结果" : "作品索引"}</h2>
        </div>
        {query ? <Link href="/novels">清除搜索</Link> : null}
      </section>
      {catalog ? (
        <NovelExplorer novels={catalog.items} />
      ) : (
        <section className="state-panel">
          <p>分析数据服务暂不可用。</p>
        </section>
      )}
    </main>
  );
}
