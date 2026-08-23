# 晋江百合小说实时研析

一个面向个人学习与非商业研究的公开分析网站，用于观察晋江文学城百合小说与作者的公开聚合元数据。
项目提供近实时快照、多指标时间轴、单指标窗口、相关矩阵、小说筛选、作者排行与运维状态，
不保存小说正文、评论内容或文案原文。

项目所属与作者：ilovemiku520@outlook.com

## 当前能力

- 交互式小说分析：按标题、作者、标签、连载状态筛选，并按收藏、书评、积分、字数或章均点击排序；
- 作者分析：按作品总收藏、总书评、总积分和作品数排行；
- 趋势可视化：支持最多三个指标的基准指数对比、单指标时间窗口与覆盖率解释；
- 变量分析：成对完整样本相关矩阵，以及中位数、四分位距、变异系数等高维统计摘要；
- 原值多轴：最多三个变量分别使用左轴、右轴和右侧外轴，按量级自动选择千、万或亿，
  同时标明求和统计或跨作品均值；
- 公开页面解析：支持 JJWXC 的 GB18030 页面，提取最小元数据；
- 单样本真实探针：一次只访问一个公开作品概览页，无登录、无 Cookie、无自动重试；
- 既有工程底座：PostgreSQL、Alembic、FastAPI、Next.js、Docker、安全门禁与审计模型。
- PostgreSQL 快照底座：迁移 `20260823_0011` 提供作者、小说当前投影、不可变指标历史和每日榜单位置表。

网站会明确区分合成 Fixture 与云数据库快照。每日任务只保存固定百合榜单及前 10 部作品的最小公开聚合元数据。

## 数据范围

允许候选字段包括：

`novel_id`、`title`、`author_id`、`author_display_name`、`novel_type`、`perspective`、
`status`、`word_count`、`review_count`、`favorite_count`、`points`、
`average_non_v_chapter_click_count`（可空）、`synopsis_char_count`、`synopsis_sentence_count`、
`synopsis_theme_terms`、`public_tags`、`observed_at`。

明确排除：文案原文、章节标题、章节正文、评论正文、读者身份、付费内容、账号凭据、Cookie、图片、
原始 HTML 与任何需要绕过访问控制的数据。

## 架构

```text
JJWXC 公开作品页（默认禁用网络）
          │ 单请求、单并发、无登录
          ▼
  最小字段解析 + Schema 检查
          │
          ▼
   候选区（不自动正式入库）
          │ 人工/规则门禁
          ▼
 PostgreSQL 快照与分析投影（迁移中）
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
- `/novels`：可交互小说分析；
- `/authors`：作者排行；
- `/analytics`：多指标时间轴、单指标窗口、相关矩阵与高维摘要；
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
