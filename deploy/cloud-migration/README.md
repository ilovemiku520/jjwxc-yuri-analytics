# JJWXC 云端迁移包

迁移包包含 PostgreSQL custom-format 备份、无敏感值环境模板、恢复脚本和校验清单。包内不保存数据库密码、
登录态、Cookie 或云端 Token。`database.dump` 仍然属于私有研究数据，只能存放在私有云盘或私有项目中。

## 当前虚拟机导出

```powershell
.\scripts\export-cloud-migration.ps1 -ContainerName yuri-postgres-1 -VerifyRestore
```

脚本会对当前数据库创建一致性逻辑备份，在同一 PostgreSQL 容器中新建随机命名的隔离数据库完成恢复演练，
核对 Alembic 版本及 JJWXC 核心表行数，然后删除该隔离数据库。源数据库不会被修改。

## 云端恢复

1. 创建一个全新的空 PostgreSQL 数据库，不要先部署 API 或运行迁移。
2. 在当前 PowerShell 进程设置 `PYURI_CLOUD_DATABASE_URL`；不要把真实连接串写入包内模板。
3. 安装 PostgreSQL 17 客户端，并执行：

```powershell
.\restore-cloud-postgres.ps1 -DumpPath .\database.dump -ConfirmEmptyTarget
```

恢复脚本先验证 SHA-256，并拒绝任何非空目标；它不使用 `--clean`，不会删除云端已有对象。成功后会生成
`cloud-restore-report.json`。随后将内部 `PYURI_DATABASE_URL`、随机导入 Token 等配置到云服务的加密变量区，
按 `deploy/railway` 配置部署 API、Web 和每日任务。
