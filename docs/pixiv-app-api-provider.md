# Pixiv App API 高效候选通道

本通道使用固定版本 `PixivPy3 3.7.5` 封装 Pixiv 的非官方 App API，面向个人、私有的
元数据研究。它与浏览器插件分工不同：插件负责登录后页面验证和单作品故障排查；App API
负责标签搜索、作者作品列表和排行的分页候选采集。

上游项目已明确说明密码登录不可用，推荐 refresh token，并提供一次约 30 个作品的分页
接口及 `next_url` 翻页方式。项目另按公开的 Pixiv OAuth PKCE 流程增加了无密码引导：

- <https://github.com/upbit/pixivpy>
- <https://pypi.org/project/pixivpy3/>
- <https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362>

## 固定边界

- 默认由用户本人在 WARP 支持的项目 Chrome 中完成登录及验证码；扩展 0.5.0 仅监听页面导航到
  Pixiv 的精确 OAuth 回调路径，并把该短时回调交给 `127.0.0.1:41180` 的一次性内存接收器；
  PKCE verifier 换票后立即清零。仍可用隐藏粘贴作为故障排查模式；
- OAuth 返回的 refresh token 不读取、不显示、不保存；access token 只存在于当前进程，最多
  租用 60 分钟。仍保留隐藏输入已有 refresh token 的兼容模式，但没有 token 命令行、环境
  变量或配置文件入口；
- 只启用 `search_illust`、`user_illusts`、`illust_ranking` 三个只读操作；
- 每分钟最多 12 页、网络并发 1、每次运行最多 100 页；每页最多 30 条，因此候选上限为
  3,000 条；
- 单页返回后最多使用 8 个本地线程做字段净化和去重；不并行扩大外部请求；
- 只输出 G0 的十二字段候选。图片 URL、图片文件、简介、收藏状态、账号字段、原始响应和
  年龄分级都不保存；
- 不自动重试。接口、认证或 Schema 发生错误时立即停止，错误输出不包含响应值；
- 输出始终是候选，`canonical_ingest_authorized=false`，不会直接进入正式数据表。

用户已在内部修订记录 `G0-2026-08-23-APP-API` 中接受非官方接口可能导致账号限制或封禁
的风险。该风险接受不授权验证码绕过、访问控制绕过、私密/删除内容采集、媒体下载、商业
使用或二次分发。

## 运行

第一次先双击一页样本入口：

```text
scripts\run-pixiv-app-api-first-sample.cmd
```

它固定搜索“百合”且只读取一页。项目会自动准备 WARP 桥接、启动一次性本机回调接收器并打开
登录页；由用户本人完成登录和验证码。登录跳转后扩展自动交接短时回调，不需要复制授权码。
接收器只监听固定环回地址、只接受扩展来源与精确 Pixiv 回调，并在收到一次回调或五分钟超时
后关闭。失败时应重新启动流程，不会自动重试。

一页验证成功后，可双击多页入口：

```text
scripts\run-pixiv-app-api-collection.cmd
```

选择标签搜索、作者作品或排行，设置 1–100 页，随后完成同一无密码 OAuth 流程。无需查看或
传递回调 URL、授权码或 token，也不要把任何此类值发到聊天、写进 `.env` 或保存到项目目录。

结果写入：

- `var/candidates/pixiv-app-api.candidate.jsonl`
- `var/reports/pixiv-app-api-collection.json`

`gppt` 已评估但未增加为运行依赖：其默认 CLI 配置/登录路径会缓存账号资料或 token；虽然
`oauth_login()` 也支持不写文件的一次性流程，本项目已经直接封装同一 PKCE 交互，并额外固定
代理、目标地址、响应大小、一次交换和 access-token 租期。当前 OAuth 引导和采集实现均已
完成；只有用户主动运行入口并完成登录时才会接触真实 App API。
