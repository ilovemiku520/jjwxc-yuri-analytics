# 浏览器导出元数据的离线导入

本路径用于接收用户在自己的浏览器中主动生成的导出文件。项目不集成登录、Cookie、
验证码绕过、动态参数逆向或图片下载。项目自带的 Manifest V3 插件位于
`apps/browser-extension`；Powerful Pixiv Downloader 仍作为可选第三方来源保留兼容。

## 边界

- Powerful Pixiv Downloader 是可选的第三方导出工具，不随本项目安装、运行或背书。
- 只使用它的 JSON“导出抓取结果”功能；不要向本项目提供账号、密码、Cookie、Token、浏览器配置或图片。
- 当前适配器只接受能由 `xRestrict=0` 证明为全年龄的记录。R-18、R-18G 和评级缺失记录均拒绝。
- 项目自带插件不负责登录。用户点击后，它优先读取当前已打开作品页已经产生的响应；
  如果响应未被观察到，只允许对当前作品发起一次同源网页接口请求。它不自动翻页、
  不下载媒体，也没有后台采集任务。
- 项目插件接受当前 G0 明确批准的 `xRestrict=0/1/2`（全年龄/R-18/R-18G）元数据。
  评级只用于准入核对，净化后的十二字段候选不会保存评级、媒体或作品正文。
- 适配器只输出批准的元数据字段。源文件中的图片 URL、描述、收藏状态、小说正文和其他字段不会写入净化结果。
- 浏览器当前页或第三方导出都不能独立证明作品的公开可见性。因此结果标记为
  `visibility_verified=false`、`canonical_ingest_authorized=false`，在另行完成来源与
  可见性审查前不能进入正式数据集。

字段映射于 2026-08-23 对 Powerful Pixiv Downloader `v19.3.0`、提交
`2afccce30c63a290e916807a5bbabf80b169e90b` 的 `ExportResult.ts` 与
`StoreType.d.ts` 做了只读核对。适配器使用明确的输入字段集合；第三方格式新增字段时会
`unsupported_source_field` 停止，必须重新审查后才能更新映射。

## 远程 Windows 主机访问

如果远程主机的上游网络对 Pixiv 返回错误 DNS 或重置 TLS，可双击：

```text
scripts\start-pixiv-browser.cmd
```

该入口要求已安装官方 Cloudflare WARP。它只启用 WARP 的回环代理模式，在
`127.0.0.1:41080` 启动项目内置桥接，并打开独立的 Chrome 资料目录。桥接仅允许
`pixiv.net`、`pximg.net`、`pixiv.org` 及其子域的 HTTPS CONNECT 请求，使用 DoH
获取地址后再通过 WARP 连接；其他域名和非 443 端口会被拒绝。入口不会修改 Windows
系统代理或默认路由，因此不会把远程桌面流量送入 WARP。

Pixiv 登录当前使用 reCAPTCHA Enterprise。桥接额外只允许 `www.recaptcha.net` 和
`www.gstatic.com` 两个精确验证资源域名，以便用户本人完成验证；它不允许其他 Google
域名，不读取验证内容，也不自动点击或提交验证码。

Chrome 会自动加载项目插件，但用户必须本人在该 Chrome 窗口完成登录。脚本和桥接不
读取、接收、保存或输出账号、密码、Cookie、Token；它们也不会自动打开作品、翻页或
采集。网络入口只解决页面可达性，不能替代来源端点审查或正式采集授权。

## 本地执行

推荐使用项目内置的无网络 Docker 入口。它不会复制原始文件，只把源文件所在目录
只读挂载到一次性容器。项目插件导出的 JSON 可以拖到
`scripts/run-pyuri-browser-companion-import.cmd`，或执行：

```powershell
.\scripts\run-pyuri-browser-companion-import.ps1 `
  -ExportPath C:\path\to\pyuri-pixiv-metadata.json
```

多个项目插件导出可以放在同一文件夹中，再把该文件夹拖到
`scripts/run-pyuri-browser-companion-batch-import.cmd`。批次最多接受 25 个文件、总计
10 MB；导入器会跨文件按作品标识去重。任一文件无效、格式混用或包含禁止字段时，整个
批次都不会输出候选数据。原始文件夹仍以只读方式挂载，导入器网络保持关闭。

Powerful Pixiv Downloader 的旧入口保持兼容：

```powershell
.\scripts\run-powerful-pixiv-import.ps1 `
  -ExportPath C:\path\to\powerful-pixiv-result.json
```

容器固定为 `network_mode: none`、只读根文件系统、删除全部 Linux capabilities，
并只写入以下两个忽略版本控制的本地结果：

- `var/candidates/browser-export.candidate.jsonl`：十二字段脱敏候选；
- `var/reports/browser-export-import.json`：只含批次哈希、文件数、计数和安全状态的审计报告。

`/operations/imports` 只读取报告中的计数和固定状态，不显示作品值、文件路径或输入哈希。
原始导出不进入数据库，也不会被复制到 `var`。

底层 CLI 会自动识别两种受支持格式，也可直接执行：

```powershell
pyuri-import-browser-export path\to\result-1.json path\to\result-2.json `
  --output var\imports\public-metadata.candidate.jsonl `
  --report var\reports\browser-export-import.json
```

输入文件只读；项目不会复制或保存原始载荷。审计报告只含批次哈希、文件数、计数和固定状态，不含作品值或文件名。输出已去除媒体 URL 和用户状态，但仍仅供个人学习或研究使用，严禁商业用途或二次分发。
