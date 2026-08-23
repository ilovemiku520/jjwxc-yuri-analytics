export default function DataPolicyPage() {
  return (
    <main className="catalog-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Data use &amp; provenance</p>
          <h1>数据使用与来源说明</h1>
        </div>
        <p>适用于 JJWXC 百合小说、作者及其公开聚合指标的非商业研究展示。</p>
      </header>
      <section className="operations-grid" aria-label="数据使用边界">
        <article className="state-panel">
          <div className="panel-heading">
            <h2>使用范围</h2>
            <span>NON-COMMERCIAL</span>
          </div>
          <p>
            数据与分析结果仅限个人学习或非商业研究使用，严禁商业用途、二次分发、转售、数据镜像或用于训练商业产品。
          </p>
        </article>
        <article className="state-panel">
          <div className="panel-heading">
            <h2>数据来源</h2>
            <span>ATTRIBUTION</span>
          </div>
          <p>
            页面会明确区分合成 Fixture 与数据库快照。数据库快照仅来自晋江文学城公开榜单及作品概览页上的作品/作者标识、类型、进度、字数、总书评数、收藏数、积分、非
            V 章节章均点击数与公开标签等聚合元数据；未公开值保持为空。
          </p>
        </article>
        <article className="state-panel">
          <div className="panel-heading">
            <h2>权利与关系</h2>
            <span>NO AFFILIATION</span>
          </div>
          <p>
            晋江文学城名称、平台内容及小说相关权利归北京晋江原创网络科技有限公司与各自权利人所有。本项目是个人独立研究项目，与晋江文学城不存在隶属、合作、背书或授权关系。
          </p>
        </article>
        <article className="state-panel">
          <div className="panel-heading">
            <h2>采集边界</h2>
            <span>AGGREGATES ONLY</span>
          </div>
          <p>
            不保存文案原文，仅即时提取长度、句数和固定主题词；不采集章节标题、正文、评论内容、读者身份、付费内容、登录态或账号凭据，不绕过访问控制。云端仅在每日固定时段启动独立低频任务，遇到阻断立即停止且不自动重试。
          </p>
        </article>
      </section>
    </main>
  );
}
