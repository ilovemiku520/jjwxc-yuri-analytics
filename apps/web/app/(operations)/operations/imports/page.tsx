import { loadJjwxcProbeView } from "../../../../lib/jjwxc/probe-report";
import { AuthorVClickImporter } from "../../../../components/jjwxc/author-v-click-importer";

const FIELDS = ["novel_id", "title", "author_id", "author_display_name", "novel_type", "perspective", "status", "word_count", "review_count", "favorite_count", "points", "public_tags", "observed_at"] as const;

export const dynamic = "force-dynamic";

export default async function ImportsPage() {
  let report: Awaited<ReturnType<typeof loadJjwxcProbeView>> | null = null;
  try { report = await loadJjwxcProbeView(); } catch {}
  const ready = report?.status === "candidate_ready";
  return (
    <main className="catalog-page">
      <header className="page-heading"><div><p className="eyebrow">JJWXC public metadata probe</p><h1>真实样本候选</h1></div><p>单次访问公开作品概览页，只提取分析所需的聚合元数据。</p></header>
      <section className="import-decision" aria-labelledby="jjwxc-probe-title">
        <div><p className="eyebrow">Current decision</p><h2 id="jjwxc-probe-title">{ready ? "公开元数据候选已生成" : report?.status === "blocked" ? "最近一次探针已安全阻止" : "单请求探针已就绪"}</h2><p>公开页与普通读者登录页都不提供 V 章节点击；V 点击只接受作品作者本人从作者后台导出的授权数据，缺失时保持为空。</p></div>
        <dl><div><dt>外部请求</dt><dd className={ready ? "safe-value" : undefined}>{report?.requestCount ?? 0} / 1</dd></div><div><dt>候选记录</dt><dd className={ready ? "safe-value" : undefined}>{report?.candidateCount ?? 0}</dd></div><div><dt>正式入库</dt><dd>BLOCKED</dd></div></dl>
      </section>
      <section className="state-panel"><div className="panel-heading"><h2>运行方式</h2><span>ONE REQUEST</span></div><p>双击 <code>scripts/run-jjwxc-public-probe.cmd</code> 可用默认样本；也可从终端传入一个公开 novelid。普通读者 Cookie 不会被用于推断或伪造 V 点击。</p></section>
      <section className="state-panel"><div className="panel-heading"><h2>允许字段</h2><span>{FIELDS.length} FIELDS</span></div><div className="tag-row">{FIELDS.map((field) => <span key={field}>{field}</span>)}</div></section>
      <AuthorVClickImporter />
      <section className="operations-grid" aria-label="JJWXC 采集边界">
        <article className="state-panel"><div className="panel-heading"><h2>来源</h2><span>PUBLIC</span></div><p>仅允许 <code>https://www.jjwxc.net/onebook.php?novelid=…</code>，拒绝跳转与其他主机。</p></article>
        <article className="state-panel"><div className="panel-heading"><h2>频率</h2><span>SERIAL</span></div><p>当前阶段单并发、单请求、零自动重试。后续批次也必须采用低频快照而非秒级实时抓取。</p></article>
        <article className="state-panel"><div className="panel-heading"><h2>内容</h2><span>NO TEXT</span></div><p>文案、章节标题、正文、评论正文、读者身份、付费内容与原始响应全部丢弃。</p></article>
        <article className="state-panel"><div className="panel-heading"><h2>用途</h2><span>PERSONAL</span></div><p>仅供个人学习或研究，严禁商业用途、二次分发或数据镜像。</p></article>
      </section>
    </main>
  );
}
