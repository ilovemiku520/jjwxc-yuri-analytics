import { formatCount } from "../../lib/format/number";
import type { JjwxcResearchIndicatorSummary } from "../../types/api";

function percentage(value: number | null): string {
  return value === null ? "数据不足" : `${(value * 100).toFixed(1)}%`;
}

function mean(value: number | null): string {
  return value === null ? "数据不足" : formatCount(Math.round(value));
}

export function ResearchIndicatorPanel({
  data,
}: {
  data: JjwxcResearchIndicatorSummary;
}) {
  return (
    <section className="chart-panel research-indicator-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">RESEARCH VALUE · COVERAGE FIRST</p>
          <h2>读者投入与内容生命周期指标</h2>
        </div>
        <span>仅计算共同有效样本，不补零</span>
      </div>
      <div className="research-kpi-grid">
        <article>
          <span>忠诚率代理</span>
          <strong>{percentage(data.loyalty_ratio)}</strong>
          <small>
            平均营养液 ÷ 平均收藏 · n={data.nutrition_observed_count}
          </small>
        </article>
        <article>
          <span>点收比中位数</span>
          <strong>{percentage(data.median_click_favorite_ratio)}</strong>
          <small>
            单部首章点击 ÷ 收藏后取中位数 · n=
            {data.click_favorite_observed_count}
          </small>
        </article>
        <article>
          <span>连载 / 完结营养液均值</span>
          <strong>
            {mean(data.serial_nutrition_mean)} /{" "}
            {mean(data.completed_nutrition_mean)}
          </strong>
          <small>
            连载 n={data.serial_nutrition_observed_count} · 完结 n=
            {data.completed_nutrition_observed_count}
          </small>
        </article>
        <article>
          <span>完结 / 连载营养液比</span>
          <strong>
            {percentage(data.completed_to_serial_nutrition_ratio)}
          </strong>
          <small>
            营养液字段覆盖率 {data.nutrition_coverage_basis_points / 100}%
          </small>
        </article>
      </div>
      <div className="indicator-framework" aria-label="研究指标获取框架">
        <article>
          <span className="indicator-tier public">公开快照</span>
          <h3>作品热度与创作节奏</h3>
          <p>
            收藏、书评、积分、字数、状态、题材、章节数、首章及非 V
            点击；营养液、推荐数、霸王票仅在公开响应确有数字时保存。
          </p>
        </article>
        <article>
          <span className="indicator-tier authorized">作者授权</span>
          <h3>付费转化与留存</h3>
          <p>
            V
            章点击、全订或订阅聚合必须由作品作者从自己的后台导入；收订比、霸王票/全订比仅在分母分子都有授权证据时计算。
          </p>
        </article>
        <article>
          <span className="indicator-tier external">外部标注</span>
          <h3>IP 改编与商业延伸</h3>
          <p>
            IP
            改编状态可由可信公开来源人工标注并附出处；版权收入属于私有商业数据，不从网页推断、不估算。
          </p>
        </article>
        <article>
          <span className="indicator-tier excluded">不采集</span>
          <h3>个人画像与内容正文</h3>
          <p>
            不采集或推断读者性别、年龄、地域和身份，不保存评论正文、章节正文；文本分析仅使用公开标签和不可还原的文案统计特征。
          </p>
        </article>
      </div>
      <details className="statistics-details statistics-requirements">
        <summary>统计与建模推进条件</summary>
        <div>
          <ul>
            <li>
              每个指标同时报告均值、中位数、四分位数与覆盖率，避免头部作品扭曲普通作品水平。
            </li>
            <li>
              月度题材趋势必须使用固定榜单口径和可追踪作品集合；队列更换不解释为市场涨跌。
            </li>
            <li>
              受欢迎度预测只有在稳定样本、明确标签、时间外验证和基线模型齐备后才开放，不用小样本生成伪预测。
            </li>
          </ul>
        </div>
      </details>
    </section>
  );
}
