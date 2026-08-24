# 晋江百合小说实时研析

一个面向个人学习与非商业研究的公开分析网站，用于观察晋江文学城百合小说与作者的公开聚合元数据。
项目提供每日增量快照、多指标时间轴、相关矩阵、全站索引搜索、双榜单、小说筛选、作者排行与
运维状态，为避免侵权，本项目不会在长期数据库中保存小说正文、评论内容或文案原文内容。

项目所属与作者：ilovemiku520@outlook.com，有问题可通过邮箱联系。

本项目只完成基础功能，尚为试行初级阶段，后续会进行ui界面和数据统计分析方法的优化。

在线网站：[https://web-production-99ad5.up.railway.app](https://web-production-99ad5.up.railway.app)

生产环境由仓库内 [`.railway/railway.ts`](.railway/railway.ts) 管理：Web 公开，API、PostgreSQL、
每日采集和每日备份保持私网；四个代码服务绑定 GitHub `main` 自动部署。密钥仅保存在 Railway。

## 当前能力

- 分层全站作品索引：分页扫描官方百合作品库，按作品名或作者名查询 PostgreSQL 中文子串索引；
- 百合频道双榜：分别保存和展示“频道金榜”“新手金榜”的每日位置；
- 交互式小说分析：按收藏、书评、积分、字数或章均点击排序；
- 作者分析：按作品总收藏、总书评、总积分和作品数排行；
- 作者专栏快照：采集非锁定/锁定作品数、作者被收藏数、非锁定作品总字数与总积分；
- 趋势可视化：支持最多三个指标的基准指数对比与覆盖率解释；
- 变量分析：成对完整样本相关矩阵，以及中位数、四分位距、变异系数等高维统计摘要；
- 原值多轴：最多三个变量分别使用左轴、右轴和右侧外轴，按量级自动选择千、万或亿，
  同时标明求和统计或跨作品均值；
- 公开页面解析：支持 JJWXC 的 GB18030 页面，提取最小元数据、文案统计特征和章节目录结构；
- 点击采集：使用作品页自身加载的公开静态响应保存逐章点击，并严格区分 V/非 V 和缺失值；
- 可恢复分层回填：频道页本次发现 412 个去重作品编号；作品库摘要分页扩展搜索面，详细页面进入队列分批补全并缓存 24 小时；
- 单样本真实探针：一次只访问一个公开作品概览页，无登录、无 Cookie、无自动重试；
- 既有工程底座：PostgreSQL、Alembic、FastAPI、Next.js、Docker、安全门禁与审计模型。
- PostgreSQL 快照底座：迁移 `20260824_0014` 提供作者专栏、小说、章节点击、双榜单、发现队列与分层搜索索引。

网站会明确区分合成 Fixture 与数据库快照。每日任务先更新双榜单与发现队列，再按固定限额持续补全
作品；初次回填完成后转为每日增量更新。

## 数据范围

允许候选字段包括：

`novel_id`、`title`、`author_id`、`author_display_name`、`novel_type`、`perspective`、
`status`、`word_count`、`review_count`、`favorite_count`、`points`、
`average_non_v_chapter_click_count`（可空）、`average_v_chapter_click_count`（可空）、V/非 V 章节数、
逐章 `chapter_id`、字数与公开点击（可空）、`synopsis_char_count`、`synopsis_sentence_count`、
`synopsis_theme_terms`、`public_tags`、双榜单位置、作者专栏公开聚合指标、`observed_at`。

分析层另行计算 `V 章均点击 / 非 V 章均点击` 的点击留存比代理。V 章均点击仅接受作品作者本人授权导出的后台统计；只有两侧章均点击同时可见且
非 V 均值大于 0 时才计算；它不是去重读者留存率，缺失值不补零，结果也不强制限制在 100%。

明确排除长期保存或公开：文案原文、章节标题、内容提要、章节正文、评论正文、读者身份、付费内容、
账号凭据、Cookie、图片与任何需要绕过访问控制的数据。原始 HTML 仅进入不公开的 24 小时压缩缓存，
用于避免重复请求和结构诊断，到期可删除。

## 架构

```text
JJWXC 百合频道 + 公开作品页 + 页面静态点击响应（默认禁用网络）
          │ 单并发、限速、无登录、24h 私有缓存
          ▼
 双榜发现 + 可恢复队列 + 最小字段/章节解析
          │
          ▼
 PostgreSQL 不可变快照 + 中文搜索索引
          │
          ▼
 FastAPI 只读接口 ── Next.js 交互式网站
```

为保留已有数据库迁移和部署兼容性，Python 内部包名暂时仍为 `pixiv_yuri`；新代码集中在
`pixiv_yuri.jjwxc`，产品名称、API 标题和网站已切换到 JJWXC。

## 本机启动

```powershell
docker compose --profile api --profile web up -d --build postgres db-migrate api web
```

浏览器打开 [http://127.0.0.1:3000](http://127.0.0.1:3000)。主要页面：

- `/`：概览与趋势；
- `/novels`：作品名/作者名搜索、频道双榜与可交互小说分析；
- `/authors`：作者排行；
- `/analytics`：多指标时间轴、相关矩阵与高维摘要；
- `/operations/imports`：真实单样本候选状态；
- `/about/data-policy`：数据使用与来源声明。

## 单个真实公开样本

双击 `scripts/run-jjwxc-public-probe.cmd`，或传入一个公开 novelid：

```powershell
.\scripts\run-jjwxc-public-probe.ps1 -NovelId 10806685
```

成功后仅生成：

- `var/candidates/jjwxc-public-novel.candidate.json`：最小化候选；
- `var/reports/jjwxc-public-probe.json`：不含字段值的状态报告。

该命令临时打开单进程网络开关，结束后恢复；不代表允许批量采集或正式入库。

## 质量检查

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_jjwxc_public_probe.py tests/test_jjwxc_api.py
.\.venv\Scripts\python.exe -m ruff check src/pixiv_yuri/jjwxc src/pixiv_yuri/api/jjwxc_api.py
.\.venv\Scripts\python.exe -m mypy src/pixiv_yuri/jjwxc src/pixiv_yuri/api/jjwxc_api.py
pnpm --filter @pyuri/web typecheck
pnpm --filter @pyuri/web lint
pnpm --filter @pyuri/web test
```

## 使用与来源声明

数据及分析结果仅限个人学习或非商业研究使用，严禁任何商业用途、二次分发、转售或数据镜像。
晋江文学城名称、平台内容及小说相关权利归平台与各自权利人所有。本项目与晋江文学城不存在隶属、
合作、背书或授权关系。

详细可行性、字段难度、robots 与条款边界见 [docs/jjwxc-feasibility.md](docs/jjwxc-feasibility.md)。
