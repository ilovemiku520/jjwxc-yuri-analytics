# 云端部署与每日快照方案

更新日期：2026-08-23

## 推荐架构

采用 Railway Hobby 单项目部署四个服务：公开 `web`、仅私网 `api`、托管 PostgreSQL、短时
`daily` 定时任务。这样保留现有 Next.js、FastAPI、Alembic 和 PostgreSQL，不在本机到期前进行
高风险重写。网站只发布聚合元数据与统计结果，不发布原始 HTML、文案原文、章节或评论内容。

`daily` 默认在北京时间每日 03:30 执行（UTC cron `30 19 * * *`）：请求一次固定的“原创·百合”
榜单，再以单并发、至少 2 秒间隔补充榜单前 10 部作品公开概览。没有自动重试；403、429、验证码、
跳转、响应过大或结构漂移均使当次任务失败退出。相同榜单、日期、作品和位置有数据库唯一约束，
重跑不会复制榜单行。

## 成本可行性

- Railway Hobby 当前最低消费为 5 美元/月，包含 5 美元用量；内存、CPU、磁盘和外网流量按量计费。
- 该项目的主要费用来自持续运行的 web、api 和 PostgreSQL；每日任务只运行几十秒，增量很小。
- 初期保守预算为 10–25 美元/月。上线一周后应依据 Railway Usage 实测，将计算支出硬上限设为
  25 美元并配置 15 美元邮件预警。
- 免费方案不适合这个交付：Railway 免费层正式期只有三个服务且没有 cron；Render 免费 PostgreSQL
  30 天到期。需要长期历史快照时，持久数据库不能依赖会自动到期的免费实例。

## 四个服务的变量

1. PostgreSQL：使用 Railway PostgreSQL 模板，保持私网。
2. `api`：配置路径 `/deploy/railway/api.railway.json`；设置
   `PYURI_DATABASE_URL=${{Postgres.DATABASE_URL}}`、`PYURI_API_HOST=0.0.0.0`、
   `PYURI_API_DEPLOYMENT_SCOPE=private_container`、`PYURI_SHARED_CONSUMER_CONTROLS_ENABLED=true`。
3. `web`：配置路径 `/deploy/railway/web.railway.json`；设置
   `PYURI_INTERNAL_API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}`，只为该服务生成公网域名。
4. `daily`：配置路径 `/deploy/railway/daily.railway.json`；设置
   `PYURI_DATABASE_URL=${{Postgres.DATABASE_URL}}` 和 `JJYURI_ENABLE_NETWORK=true`，不生成公网域名。

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
