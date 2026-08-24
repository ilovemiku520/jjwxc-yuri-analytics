import Link from "next/link";

import { CatalogSearchResults } from "../../../components/jjwxc/catalog-search-results";
import { ChannelRankings } from "../../../components/jjwxc/channel-rankings";
import { NovelExplorer } from "../../../components/jjwxc/novel-explorer";
import { fetchApi } from "../../../lib/api/client";
import type {
  JjwxcChannelRankingResponse,
  JjwxcFullCatalogSearchResponse,
  JjwxcNovelPage,
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
  const [searchResult, catalogResult, goldResult, newcomerResult] = await Promise.allSettled([
    query
      ? fetchApi<JjwxcFullCatalogSearchResponse>(
          `/api/v1/jjwxc/catalog-search?query=${encodeURIComponent(query)}&limit=100`,
        )
      : Promise.resolve(null),
    query
      ? Promise.resolve(null)
      : fetchApi<JjwxcNovelPage>("/api/v1/jjwxc/novels?sort=favorites&limit=200"),
    fetchApi<JjwxcChannelRankingResponse>(
      "/api/v1/jjwxc/channel-rankings?ranking_key=channel_gold",
    ),
    fetchApi<JjwxcChannelRankingResponse>(
      "/api/v1/jjwxc/channel-rankings?ranking_key=newcomer",
    ),
  ]);
  const searchCatalog = searchResult.status === "fulfilled" ? searchResult.value : null;
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
          标题与作者名检索直接查询后端索引；作品库摘要与详细分析分层补全，浏览器不会直接请求晋江。
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
            ? `“${query}”在全站增量索引中找到 ${searchCatalog?.total ?? 0} 条结果`
            : "当前展示详细快照；作品库分页扫描会持续扩大可搜索范围。"}
        </p>
      </form>

      {query ? (
        <section className="catalog-search-results" aria-labelledby="search-results-title">
          <div className="catalog-results-heading">
            <div>
              <p className="eyebrow">Searchable catalog</p>
              <h2 id="search-results-title">搜索结果</h2>
            </div>
            <Link href="/novels">清除搜索</Link>
          </div>
          {searchCatalog ? (
            <CatalogSearchResults items={searchCatalog.items} />
          ) : (
            <section className="state-panel">
              <p>索引搜索服务暂不可用。</p>
            </section>
          )}
        </section>
      ) : null}

      <ChannelRankings channelGold={gold} newcomer={newcomer} />

      {!query ? (
        <>
          <section className="catalog-results-heading">
            <div>
              <p className="eyebrow">Searchable catalog</p>
              <h2>作品索引</h2>
            </div>
          </section>
          {catalog ? (
            <NovelExplorer novels={catalog.items} />
          ) : (
            <section className="state-panel">
              <p>分析数据服务暂不可用。</p>
            </section>
          )}
        </>
      ) : null}
    </main>
  );
}
