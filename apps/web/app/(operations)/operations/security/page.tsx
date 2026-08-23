import { fetchApi } from "../../../../lib/api/client";
import { formatCount, formatDateTime } from "../../../../lib/format/number";
import type { ConsumerSecurityStatus } from "../../../../types/api";

export const dynamic = "force-dynamic";

function yesNo(value: boolean): string {
  return value ? "已配置" : "未配置";
}

export default async function SecurityStatusPage() {
  let status: ConsumerSecurityStatus | null = null;
  try {
    status = await fetchApi<ConsumerSecurityStatus>("/api/v1/operations/security-status");
  } catch {
    // Render the fixed private-service failure state below.
  }

  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div><p className="eyebrow">Consumer controls</p><h1>消费者安全状态</h1></div>
        <p>仅显示聚合控制状态；消费者哈希、请求 ID 和路由记录不会进入页面。</p>
      </header>
      {status ? (
        <>
          <dl className="security-grid" aria-label="消费者安全控制">
            <div className="security-card"><dt>共享限流</dt><dd>{status.shared_rate_limit_backend === "postgres" ? "PostgreSQL" : "未启用"}<small>{formatCount(status.rate_limit_window_count)} 个活动摘要窗口</small></dd></div>
            <div className="security-card"><dt>持久审计</dt><dd>{status.durable_access_audit_sink === "postgres" ? "PostgreSQL" : "结构化日志"}<small>{formatCount(status.audit_event_count)} 条最小化事件</small></dd></div>
            <div className="security-card"><dt>审计保留</dt><dd>{status.audit_retention_days} 天<small>每条事件均带明确到期时间</small></dd></div>
            <div className="security-card"><dt>身份适配器</dt><dd>{yesNo(status.identity_adapter_configured)}<small>配置前不允许外部消费者访问</small></dd></div>
          </dl>
          <section className="state-panel security-decision">
            <div className="panel-heading"><h2>发布决定</h2><span>FAIL CLOSED</span></div>
            <p>{status.external_publication_approved ? "已批准" : "未批准外部发布"}</p>
            <p>最早审计：{status.oldest_audit_at ? formatDateTime(status.oldest_audit_at) : "尚无"}；最近审计：{status.latest_audit_at ? formatDateTime(status.latest_audit_at) : "尚无"}。</p>
          </section>
        </>
      ) : <section className="state-panel"><p>消费者安全状态 API 暂不可用。</p></section>}
    </main>
  );
}
