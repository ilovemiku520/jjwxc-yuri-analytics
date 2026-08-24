import Link from "next/link";

import { JjwxcTrendChart } from "../../components/charts/jjwxc-trend-chart";
import { StatCard } from "../../components/ui/stat-card";
import { fetchApi } from "../../lib/api/client";
import { formatCount } from "../../lib/format/number";
import type {
  JjwxcNovelPage,
  JjwxcOverview,
  JjwxcTrendResponse,
} from "../../types/api";

export const dynamic = "force-dynamic";
const DASHBOARD_RANKING_OPTIONS = [10, 20, 50] as const;
const DASHBOARD_RANKING_DEFAULT = DASHBOARD_RANKING_OPTIONS[1];
type SearchParams = Promise<{ top?: string | string[] }>;

function firstValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function parseDashboardLimit(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return DASHBOARD_RANKING_OPTIONS.includes(parsed as (typeof DASHBOARD_RANKING_OPTIONS)[number])
    ? parsed
    : DASHBOARD_RANKING_DEFAULT;
}

async function loadOverview(rankingLimit: number) {
  const [overview, ranking, trends] = await Promise.all([
    fetchApi<JjwxcOverview>("/api/v1/jjwxc/overview"),
    fetchApi<JjwxcNovelPage>(
      `/api/v1/jjwxc/novels?sort=favorites&limit=${rankingLimit}`,
    ),
    fetchApi<JjwxcTrendResponse>("/api/v1/jjwxc/trends"),
  ]);
  return { overview, ranking, trends };
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const rankingLimit =
    parseDashboardLimit(firstValue((await searchParams).top));
  let data: Awaited<ReturnType<typeof loadOverview>> | null = null;
  try {
    data = await loadOverview(rankingLimit);
  } catch {
    // A stopped private API renders an explicit local-only fallback.
  }

  return (
    <main className="dashboard">
      <section className="hero jjwxc-hero">
        <div>
          <p className="eyebrow">JJWXC yuri novel observatory</p>
          <h1>
            百合小说的
            <br />
            <em>近实时脉搏</em>
          </h1>
        </div>
        <div className="hero-copy">
          <p>
            聚焦晋江文学城百合小说及作者的公开聚合元数据，观察收藏、书评、字数与积分变化。
          </p>
          <p>不采集正文、评论内容、付费章节或账号信息；仅每日低频保存最小公开元数据。</p>
        </div>
      </section>

      {data ? (
        <>
          <section className="stat-grid" aria-label="JJWXC 数据规模">
            <StatCard
              label="小说样本"
              value={formatCount(data.overview.novel_count)}
              note="当前验证快照"
            />
            <StatCard
              label="作者"
              value={formatCount(data.overview.author_count)}
              note="公开作者标识"
            />
            <StatCard
              label="总字数"
              value={formatCount(data.overview.total_word_count)}
              note="样本内公开字数"
            />
            <StatCard
              label="总书评"
              value={formatCount(data.overview.total_review_count)}
              note="仅聚合计数"
            />
          </section>
          <section className="content-grid">
            <article className="ranking-panel">
              <div className="panel-heading">
                <h2>收藏热度</h2>
                <Link className="muted-link" href="/novels">
                  打开交互分析 →
                </Link>
              </div>
              <form action="/" className="cohort-search" method="get">
                <label htmlFor="dashboard-ranking-top">展示条数</label>
                <div>
                  <select
                    id="dashboard-ranking-top"
                    name="top"
                    defaultValue={String(rankingLimit)}
                  >
                    {DASHBOARD_RANKING_OPTIONS.map((option) => (
                      <option key={option} value={String(option)}>
                        前 {option} 部
                      </option>
                    ))}
                  </select>
                  <button type="submit">更新</button>
                </div>
              </form>
              <ol className="ranking-list">
                {data.ranking.items.map((novel, index) => (
                  <li key={novel.novel_id}>
                    <span className="rank-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span>
                      <Link
                        className="rank-title"
                        href={`/novels/${novel.novel_id}`}
                      >
                        {novel.title}
                      </Link>
                      <span className="rank-meta">
                        {novel.author_display_name} · {novel.status}
                      </span>
                    </span>
                    <span className="rank-score">
                      {formatCount(novel.favorite_count)}
                    </span>
                  </li>
                ))}
              </ol>
              <p className="analysis-note">
                当前展示前 {Math.min(data.ranking.items.length, rankingLimit)} 部，全部样本{" "}
                {formatCount(data.overview.novel_count)} 部
              </p>
              <Link className="muted-link" href="/novels">
                查看全部榜单 →
              </Link>
            </article>
            <aside className="state-panel">
              <div className="panel-heading">
                <h2>数据边界</h2>
                <span>
                  {data.overview.data_mode === "database_snapshot"
                    ? "DATABASE SNAPSHOT"
                    : "FIXTURE"}
                </span>
              </div>
              <p>
                {data.overview.data_mode === "database_snapshot"
                  ? "当前看板读取云数据库的每日最小公开元数据快照；未公开字段保持为空。"
                  : "当前看板使用合成数据验证交互链路，所有数值均为演示。"}
              </p>
              <p>
                最近快照：
                {new Intl.DateTimeFormat("zh-CN", {
                  dateStyle: "medium",
                  timeStyle: "short",
                  timeZone: "Asia/Shanghai",
                }).format(new Date(data.overview.latest_observed_at))}
              </p>
              <p>真实更新目标：低频批次快照，不宣称秒级实时。</p>
            </aside>
          </section>
          <section className="chart-panel" id="trend">
            <div className="panel-heading">
              <h2>书评与收藏趋势</h2>
              <Link className="muted-link" href="/analytics">
                打开多变量分析 →
              </Link>
            </div>
            <JjwxcTrendChart items={data.trends.items} />
          </section>
        </>
      ) : (
        <section className="state-panel" aria-live="polite">
          <div className="panel-heading">
            <h2>分析数据服务暂不可用</h2>
            <span>SAFE FALLBACK</span>
          </div>
          <p>接口恢复后刷新页面；浏览器不会直接访问晋江文学城。</p>
        </section>
      )}
    </main>
  );
}
