# 候选导入的人工可见性审查

浏览器导出与 App API 适配器生成的都是净化后的候选数据，不能自动证明每条作品符合已批准的可见性范围。本门禁将四项独立事实绑定：净化导出/采集报告、候选 JSONL 文件、人工审查件和已经通过的来源端点审查。

它不访问网页、不索取凭据、不写入数据库，也不会直接将候选数据加入正式目录。

## 审查件

从 `config/candidate_visibility_review.template.json` 复制一份本机文件。仅填写审查标识、时间、哈希、数量和无 URL 的审查参考；不要写入作品链接、账号、Cookie、Token、图片或响应内容。审查件最长有效七天。

## 验证

```powershell
pyuri-review-candidate `
  --candidate var\candidates\browser-export.candidate.jsonl `
  --import-report var\reports\browser-export-import.json `
  --review-artifact path\to\candidate_visibility_review.json `
  --source-endpoint-review var\reports\source_endpoint_review.json `
  --output var\reports\candidate-import-review.json
```

旧命令名 `pyuri-review-browser-candidate` 继续兼容。App API 候选使用
`var/reports/pixiv-app-api-collection.json` 作为 `--import-report`，最多 3,000 条；审查器还会
核对页数与记录计数、认证模式、零密码/secret/raw/media 落盘、零自动重试和网络并发 1。

只有活动 G0 指纹、审查件、候选文件、导入/采集报告和来源端点合同全部匹配且均未过期时，报告才会显示 `canonical_ingest_authorized=true`。项目浏览器插件与 App API 候选允许人工记录 G0 已批准的全年龄、R-18、R-18G 范围；旧版 Powerful Pixiv Downloader 适配器仍只允许全年龄。当前没有已审查的实际 Pixiv 端点合同，因此对任何真实候选都会安全返回 `blocked`。
