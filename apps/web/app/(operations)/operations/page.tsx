import Link from "next/link";

const SECTIONS = [
  ["部署就绪", "Phase 6 控制矩阵、恢复证据与发布阻塞项。", "/operations/readiness"],
  ["JJWXC 样本探针", "公开聚合元数据的单请求候选状态。", "/operations/imports"],
  ["Schema 生命周期", "结构指纹、样本数与解析器兼容范围。", "/operations/schemas"],
  ["运行状态", "离线运行及其成功、失败任务计数。", "/operations/runs"],
  ["任务状态", "优先级、尝试次数与固定机器错误码。", "/operations/tasks"],
  ["消费者安全", "共享限流、最小化审计与发布门禁状态。", "/operations/security"],
  ["隔离队列", "不包含来源标识和错误自由文本的审查摘要。", "/operations/quarantine"],
] as const;

export default function OperationsPage() {
  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Read-only operations</p><h1>私有运维视图</h1></div>
        <p>仅展示最小化状态摘要；这里没有重试、解析、采集或队列变更操作。</p>
      </header>
      <section className="operations-grid" aria-label="运维功能">
        {SECTIONS.map(([title, description, href]) => (
          <Link className="operations-card" href={href} key={href}>
            <span>GET ONLY</span>
            <h2>{title}</h2>
            <p>{description}</p>
          </Link>
        ))}
      </section>
    </main>
  );
}
