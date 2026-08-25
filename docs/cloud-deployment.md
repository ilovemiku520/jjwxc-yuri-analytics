# 云端部署与每日快照方案

更新日期：2026-08-24

## 推荐架构

采用 Railway 单项目部署五个服务：公开 `web`、仅私网 `api`、托管 PostgreSQL、短时
`daily` 定时任务与逻辑备份任务 `backup`。这样保留现有 Next.js、FastAPI、Alembic 和 PostgreSQL，不在本机到期前进行
高风险重写。网站只发布聚合元数据与统计结果，不发布原始 HTML、文案原文、章节或评论内容。

`daily` 默认在北京时间每日 03:30 执行（UTC cron `30 19 * * *`）：读取百合频道首页的“频道金榜”
与“新手金榜”，再从官方作品库断点扫描 10 页摘要，并把发现的作品编号加入可恢复队列；随后以单并发、
至少 2 秒间隔补全每天最多 39 部作品详情和 100 位作者专栏，保存文案统计特征、章节 V/非 V 标识、
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
- Trial 到期后会转为每月 1 美元额度的 Free，该额度预计不足以让 Web、API 与 PostgreSQL 整月常驻。
  需要长期历史快照时，持久数据库不能依赖会自动到期的免费额度。

## 五个服务的变量

1. PostgreSQL：使用 Railway PostgreSQL 模板，保持私网。
2. `api`：由仓库内 `/.railway/railway.ts` 管理；设置
   `PYURI_DATABASE_URL=${{Postgres.DATABASE_URL}}`、`PYURI_API_HOST=0.0.0.0`、
   `PYURI_API_DEPLOYMENT_SCOPE=private_container`、`PYURI_SHARED_CONSUMER_CONTROLS_ENABLED=true`，并生成
   高熵随机值 `PYURI_COHORT_IMPORT_TOKEN`（不得提交仓库）。
3. `web`：由仓库内 `/.railway/railway.ts` 管理；设置
   `PYURI_INTERNAL_API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}`，并设置与 api 完全相同的
   `PYURI_COHORT_IMPORT_TOKEN`；只为该服务生成公网域名。
4. `daily`：由仓库内 `/.railway/railway.ts` 管理；设置
   `PYURI_DATABASE_URL=${{Postgres.DATABASE_URL}}` 和 `JJYURI_ENABLE_NETWORK=true`，不生成公网域名；挂载
   Volume 到 `/data/cache`。由于 Railway Volume 以 root 挂载，`daily` 通过
   `RAILWAY_RUN_UID=0` 创建缓存目录；API 与 Web 仍以非 root 用户运行。可用 `--index-pages`
   与 `JJYURI_HYDRATE_LIMIT` 控制摘要扫描和详细补全量；默认生产命令扫描 10 页、补全 39 部作品
   与 10 位作者，使单次运行请求上界为 99 次。
5. `backup`：由仓库内 `/.railway/railway.ts` 管理；设置
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`，不生成公网域名；挂载 500MB Volume 到 `/backups`。
   UTC 每日 20:30（北京时间次日 04:30）执行 `pg_dump` custom-format 逻辑备份，先用
   `pg_restore --list` 校验再原子改名，并保留最近 7 份及其 SHA-256 文件。

Railway 为每个服务使用同一 GitHub 仓库的 `main` 分支；`/.railway/railway.ts` 固化各服务的
Dockerfile、监听路径、新加坡副本、健康检查、迁移命令、Cron、持久卷和密钥占位。密钥使用
`preserve()` 保留在 Railway，不写入代码。数据库迁移由 api 的 pre-deploy 步骤执行。

## 到期前迁移顺序

1. 将当前目录建立为 Git 仓库并推送到私有远程仓库；不得提交 `.env`、数据库密码或运行时报告。
2. 在 Railway 创建项目、PostgreSQL 及四个代码服务，并按上文绑定配置与变量。
3. 先部署 api，再部署 web；确认网页可访问后手动触发 daily。
4. 从本机 PostgreSQL 导出一次压缩备份并上传到独立云盘；代码仓库不能替代数据库备份。
5. 配置消费硬上限和失败通知，确认次日 03:30 的第二个快照后，才把本机视为可丢弃环境。

### 生成可验证迁移包

在当前数据库容器健康时运行：

```powershell
.\scripts\export-cloud-migration.ps1 -ContainerName yuri-postgres-1 -VerifyRestore
```

输出位于 `var/releases/jjwxc-cloud-migration-*.zip`，另有同名 `.sha256` 文件。脚本会对真实当前数据库执行
custom-format 备份，并在随机命名的隔离数据库中完成一次恢复演练；验证 Alembic 版本与 JJWXC 核心表行数后，
隔离数据库会被删除，源库保持不变。迁移包包含恢复脚本与无密钥环境模板，但数据库备份本身仍是私有研究数据，
不得上传到公开仓库。

### 生成源代码发布包并预检 Railway

```powershell
.\scripts\build-cloud-source-release.ps1
```

该命令先校验 API、Web、daily、backup 四份 Railway 配置、Dockerfile、健康检查、数据库迁移命令、UTC Cron 与
采集请求上界，再用 Git 的已跟踪/未忽略文件清单打包当前工作区。发布包会包含尚未提交的新模块，但排除
`.env`、Git 历史、数据库备份、缓存、日志、虚拟环境和依赖目录，并用本机 `.env` 的值执行不回显内容的
泄漏扫描。输出位于 `var/releases/jjwxc-source-release-*.zip`。

四份 `deploy/railway/*.railway.json` 仅保留为离线迁移包和旧环境兼容输入。生产环境已经迁移到
Railway Infrastructure as Code；提交前运行 `railway config plan`，确认无资源删除后再运行
`railway config apply`。四个代码服务都绑定 GitHub `main`，后续匹配监听路径的提交会自动构建部署。

## 2026-08-24 实际部署状态

- Railway 项目 `jjwxc-yuri-analytics` 的 PostgreSQL、`api`、`web` 均已部署到新加坡
  `asia-southeast1-eqsg3a`，数据库只走私网且使用 500MB 持久卷。
- 公网仅开放 Web：`https://web-production-99ad5.up.railway.app`；API 和 PostgreSQL 没有持久公网入口。
- Alembic 已升级至 `20260824_0014`。一次性云端小样本任务在私网完成：发现频道作品 407 部、
  保存两个榜单共 20 个位置、扫描作品库摘要 99 条、补全 5 部作品的 725 条章节记录和 2 位作者资料，
  失败作品为 0，观测日为 2026-08-24。
- 首页、小说、分析、作者、数据政策和运行状态六个公网页面均通过 HTTP 200 验证；首页可见 5 部
  实际采集作品，作者页可见 5 位作者，所有页面保留个人研究和非商业声明。
- 当前工作区仍为 Railway Trial（30 天或 5 美元额度），没有绑定信用卡。按 Railway 当前每项目最多
  5 个 Trial 服务的规则，`daily` 已作为第 4 个服务部署到新加坡；它没有公网域名，不常驻运行，挂载
  500MB `daily-volume` 到 `/data/cache`，并以 UTC `30 19 * * *`（北京时间每日 03:30）执行。
- `backup` 已作为第 5 个且最后一个 Trial 服务部署到新加坡；它没有公网域名，挂载第三个 500MB Trial
  卷 `/backups`。首份 `jjwxc-20260824T104711Z.dump` 已通过 `pg_restore --list` 校验，大小 136287 字节；
  后续每天 04:30 执行并保留最近 7 份。
- `api`、`web`、`daily`、`backup` 已绑定 GitHub 仓库 `ilovemiku520/jjwxc-yuri-analytics` 的 `main`
  分支；生产构建与部署规则已迁入 `/.railway/railway.ts`，云端不再依赖这台虚拟机上传代码快照。
- 下一项线上证据是核对 2026-08-25 首次自动运行结果及第二个观测日快照。Trial 结束后会转为每月
  1 美元额度的 Free，但当前三项常驻服务预计不能整月维持；必须在额度结束前完成数据库备份或迁移。

## 发布边界

评级名称固定为“公开数据表现等级”，只代表当前选定时间与榜单样本中的相对位置，不代表文学质量、
作者能力或平台官方评价。公开站点必须持续展示非商业研究、数据来源、非官方关系及禁止二次分发声明。
