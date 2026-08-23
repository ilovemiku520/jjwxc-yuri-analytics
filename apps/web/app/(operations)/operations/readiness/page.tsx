import { ReadinessConsole } from "../../../../components/operations/readiness-console";
import { loadReadinessView } from "../../../../lib/readiness/report";

export const dynamic = "force-dynamic";

export default async function ReadinessPage() {
  let data: Awaited<ReturnType<typeof loadReadinessView>> | null = null;
  try {
    data = await loadReadinessView();
  } catch {
    // Render the fixed local-only failure state below.
  }
  return (
    <main className="catalog-page">
      <header className="page-heading readiness-heading">
        <div><p className="eyebrow">Deployment control room</p><h1>部署就绪控制台</h1></div>
        <p>交互查看本机 Phase 6 审查、恢复证据与发布边界。所有控件均为只读探索。</p>
      </header>
      {data ? <ReadinessConsole data={data} /> : (
        <section className="state-panel"><div className="panel-heading"><h2>本机审查报告不可用</h2><span>SAFE FALLBACK</span></div><p>界面不会使用远程数据或推断生产批准。</p></section>
      )}
    </main>
  );
}
