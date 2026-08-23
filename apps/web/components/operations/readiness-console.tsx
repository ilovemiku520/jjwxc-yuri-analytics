"use client";

import { useMemo, useState } from "react";

import type { ReadinessViewData } from "../../lib/readiness/report";

type View = "overview" | "controls" | "evidence";
type Filter = "all" | "passed" | "blocked";

const CONTROL_LABELS: Record<string, string> = {
  private_phase_evidence: "私有阶段证据",
  internal_compose_network: "内部容器网络",
  loopback_only_ports: "仅回环端口",
  collection_network_disabled: "采集网络关闭",
  service_healthchecks: "服务健康检查",
  non_root_images: "非 root 镜像",
  immutable_app_containers: "不可变应用容器",
  non_placeholder_database_secret: "运行时数据库密钥",
  backup_restore_drill: "隔离备份恢复",
  operator_runbook: "运维手册",
  production_identity_and_tls: "生产身份与 TLS",
  external_publication_approval: "外部发布批准",
};

export function ReadinessConsole({ data }: Readonly<{ data: ReadinessViewData }>) {
  const [view, setView] = useState<View>("overview");
  const [filter, setFilter] = useState<Filter>("all");
  const controls = useMemo(
    () =>
      data.controls.filter((control) => {
        if (filter === "passed") return control.passed;
        if (filter === "blocked") return !control.passed;
        return true;
      }),
    [data.controls, filter],
  );
  const blockedCount = data.controlCount - data.passedCount;

  return (
    <div className="readiness-console">
      <div className="readiness-tabs" role="tablist" aria-label="就绪控制台视图">
        {(["overview", "controls", "evidence"] as const).map((item) => (
          <button
            aria-selected={view === item}
            key={item}
            onClick={() => setView(item)}
            role="tab"
            type="button"
          >
            {item === "overview" ? "总览" : item === "controls" ? "控制矩阵" : "证据"}
          </button>
        ))}
      </div>

      {view === "overview" ? (
        <section className="readiness-overview" aria-label="Phase 6 总览">
          <div className="readiness-score" style={{ "--progress": `${data.completion * 3.6}deg` } as React.CSSProperties}>
            <strong>{data.completion}%</strong>
            <span>Phase {data.phase}</span>
          </div>
          <div className="readiness-summary">
            <p className="eyebrow">Private deployment readiness</p>
            <h2>本地控制已就绪，发布仍保持关闭</h2>
            <p>
              {data.passedCount} 项控制通过，{blockedCount} 项责任关卡待完成。界面只读取本机审查报告，
              不会触发部署、采集或审批。
            </p>
            <button className="readiness-primary" onClick={() => { setFilter("blocked"); setView("controls"); }} type="button">
              查看 {blockedCount} 个阻塞项
            </button>
          </div>
          <dl className="readiness-kpis">
            <div><dt>控制通过</dt><dd>{data.passedCount}/{data.controlCount}</dd></div>
            <div><dt>真实采集</dt><dd className="safe-value">关闭</dd></div>
            <div><dt>外部发布</dt><dd className="safe-value">未批准</dd></div>
          </dl>
        </section>
      ) : null}

      {view === "controls" ? (
        <section aria-label="部署控制矩阵">
          <div className="readiness-filter" aria-label="控制状态筛选">
            {(["all", "passed", "blocked"] as const).map((item) => (
              <button aria-pressed={filter === item} key={item} onClick={() => setFilter(item)} type="button">
                {item === "all" ? "全部" : item === "passed" ? "已通过" : "阻塞"}
              </button>
            ))}
          </div>
          <div className="control-matrix">
            {controls.map((control) => (
              <article className={`control-row ${control.passed ? "is-passed" : "is-blocked"}`} key={control.name}>
                <span className="control-state" aria-label={control.passed ? "已通过" : "阻塞"}>{control.passed ? "✓" : "!"}</span>
                <div><h3>{CONTROL_LABELS[control.name] ?? control.name}</h3><p>{control.evidence}</p></div>
                <span className="status-pill">{control.passed ? "已通过" : "等待责任证据"}</span>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {view === "evidence" ? (
        <section className="evidence-grid" aria-label="就绪证据摘要">
          <article><span>BACKUP</span><h3>隔离恢复通过</h3><p>{data.backup.rows} 行逐表一致 · Schema {data.backup.schemaVersion}</p><strong>{data.backup.checksumVerified ? "SHA-256 已验证" : "校验缺失"}</strong></article>
          <article><span>IDENTITY + TLS</span><h3>生产证据阻塞</h3><p>{data.production.unresolvedCount} 项生产控制尚未解决，本机 smoke 不会被当作生产证明。</p><strong>等待真实部署审查</strong></article>
          <article><span>PUBLICATION BINDING</span><h3>发布绑定阻塞</h3><p>{data.publicationBinding.unresolvedCount} 项绑定不满足；当前仅匹配 {data.publicationBinding.matchedCount} 个非秘密字段。</p><strong>不会授予发布权</strong></article>
          <article><span>BOUNDARY</span><h3>权限未扩大</h3><p>真实来源采集与外部发布均保持关闭；查看本页不会改变任何系统状态。</p><strong>FAIL CLOSED</strong></article>
        </section>
      ) : null}
    </div>
  );
}
