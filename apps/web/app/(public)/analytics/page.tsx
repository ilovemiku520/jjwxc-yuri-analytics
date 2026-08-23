import { MultivariateExplorer } from "../../../components/jjwxc/multivariate-explorer";
import { RatingExplorer } from "../../../components/jjwxc/rating-explorer";
import { fetchApi } from "../../../lib/api/client";
import type {
  JjwxcMultivariateResponse,
  JjwxcRatingResponse,
} from "../../../types/api";

export const dynamic = "force-dynamic";

export default async function AnalyticsPage() {
  let data: JjwxcMultivariateResponse | null = null;
  let ratings: JjwxcRatingResponse | null = null;
  try {
    [data, ratings] = await Promise.all([
      fetchApi<JjwxcMultivariateResponse>("/api/v1/jjwxc/analytics/multivariate"),
      fetchApi<JjwxcRatingResponse>("/api/v1/jjwxc/analytics/ratings"),
    ]);
  } catch {
    // Keep the private UI readable when its local API is stopped.
  }

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
            同一时间轴最多并列三个指标；更多维度改用矩阵和稳健统计摘要，避免把高维关系硬塞进不可读的三维图。
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
