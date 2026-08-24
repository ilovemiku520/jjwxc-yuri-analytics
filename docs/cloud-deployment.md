# 云端部署与每日快照方案

更新日期：2026-08-23

## 推荐架构

采用 Railway Hobby 单项目部署四个服务：公开 `web`、仅私网 `api`、托管 PostgreSQL、短时
`daily` 定时任务。这样保留现有 Next.js、FastAPI、Alembic 和 PostgreSQL，不在本机到期前进行
高风险重写。网站只发布聚合元数据与统计结果，不发布原始 HTML、文案原文、章节或评论内容。

`daily` 默认在北京时间每日 03:30 执行（UTC cron `30 19 * * *`）：读取百合频道首页的“频道金榜”
与“新手金榜”，再从官方作品库断点扫描 10 页摘要，并把发现的作品编号加入可恢复队列；随后以单并发、
至少 2 秒间隔补全每天最多 39 部作品详情和 10 位作者专栏，保存文案统计特征、章节 V/非 V 标识、
公开逐章点击及作者公开聚合指标。任务会逐日完成积压，而不是
一次无边界压满来源站。403、429、验证码、跳转、响应过大或结构漂移不会触发高速重试；失败作品
至少 6 小时后才可重试。相同榜单、日期、作品、位置和章节有数据库唯一约束，重跑不会复制数据。

原始页面与点击响应只保存在不对外提供的 24 小时压缩缓存中，长期数据库不保存文案原文、章节标题、
内容提要、正文或评论。生产 `daily` 服务应挂载一个 500MB Volume 到 `/data/cache`；没有 Volume 时
任务仍可运行，但部署重建后缓存会丢失。标题与作者名使用 PostgreSQL `pg_trgm` 索引支持中文子串搜索。

## 成本可行性

- Railway Hobby 当前最低消费为 5 美元/月，包含 5 美元用量；内存、CPU、磁盘和外网流量按量计费。
- 该项目的主要费用来自持续运行的 web、api 和 PostgreSQL；每日任务只运行几十秒，增量很小。
- 初期保守预算为 10–25 美元/月。上线一周后应依据 Railway Usage 实测，将计算支出硬上限设为
  25 美元；本项目不配置邮件提醒，费用由 Railway 控制台手动检查。
- 免费方案不适合这个交付：Railway 免费层正式期只有三个服务且没有 cron；Render 免费 PostgreSQL
  30 天到期。需要长期历史快照时，持久数据库不能依赖会自动到期的免费实例。

## 四个服务的变量

1. PostgreSQL：使用 Railway PostgreSQL 模板，保持私网。
2. `api`：配置路径 `/deploy/railway/api.railway.json`；设置
   `PYURI_DATABASE_URL=${{Postgres.DATABASE_URL}}`、`PYURI_API_HOST=0.0.0.0`、
   `PYURI_API_DEPLOYMENT_SCOPE=private_container`、`PYURI_SHARED_CONSUMER_CONTROLS_ENABLED=true`，并生成
   高熵随机值 `PYURI_COHORT_IMPORT_TOKEN`（不得提交仓库）。
3. `web`：配置路径 `/deploy/railway/web.railway.json`；设置
   `PYURI_INTERNAL_API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}`，并设置与 api 完全相同的
   `PYURI_COHORT_IMPORT_TOKEN`；只为该服务生成公网域名。
4. `daily`：配置路径 `/deploy/railway/daily.railway.json`；设置
   `PYURI_DATABASE_URL=${{Postgres.DATABASE_URL}}` 和 `JJYURI_ENABLE_NETWORK=true`，不生成公网域名；挂载
   Volume 到 `/data/cache`。可用 `--index-pages` 与 `JJYURI_HYDRATE_LIMIT` 控制摘要扫描和详细补全量；
   默认生产命令扫描 10 页、补全 39 部作品与 10 位作者，使单次运行请求上界为 99 次。

Railway 为每个服务使用同一代码仓库根目录；三个配置文件在服务 Settings 的 Config File 中分别指定。
数据库迁移由 api 的 pre-deploy 步骤执行。生产环境先运行 daily 的 dry-run，再手动触发一次正式任务并
核对榜单行数、作品快照数与网站数据来源标识。

## 到期前迁移顺序

1. 将当前目录建立为 Git 仓库并推送到私有远程仓库；不得提交 `.env`、数据库密码或运行时报告。
2. 在 Railway 创建项目、PostgreSQL 及三个代码服务，并按上文绑定配置与变量。
3. 先部署 api，再部署 web；确认网页可访问后手动触发 daily。
4. 从本机 PostgreSQL 导出一次压缩备份并上传到独立云盘；代码仓库不能替代数据库备份。
5. 配置消费硬上限和失败通知，确认次日 03:30 的第二个快照后，才把本机视为可丢弃环境。

## 发布边界

评级名称固定为“公开数据表现等级”，只代表当前选定时间与榜单样本中的相对位置，不代表文学质量、
作者能力或平台官方评价。公开站点必须持续展示非商业研究、数据来源、非官方关系及禁止二次分发声明。
