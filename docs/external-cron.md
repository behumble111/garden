# 花园兑换码云端定时

当前云端方案使用 GitHub Actions 短任务模式：每次运行只检查一个时间点，不再启动一个 runner 等完整晚。外部 cron 服务主动调用 `workflow_dispatch` 仍然是主定时器，GitHub `schedule` 配置了同一组时间作为备用。

推送正文会标出来源：

- `来源：云端 GitHub`
- `来源：本地 Windows`

## GitHub Token

创建一个 GitHub fine-grained personal access token：

- Repository access: `behumble111/garden`
- Permissions:
  - Actions: Read and write
  - Contents: Read-only

不要把 token 写进仓库文件。只在外部定时器的 HTTP Header 里保存。

## HTTP 请求

外部定时器每条任务都使用：

- Method: `POST`
- URL: `https://api.github.com/repos/behumble111/garden/actions/workflows/garden-xhs-cloud.yml/dispatches`
- Header:
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <YOUR_GITHUB_TOKEN>`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `Content-Type: application/json`

Body 模板：

```json
{
  "ref": "main",
  "inputs": {
    "slot": "20",
    "attempt": "1",
    "date": "",
    "dry_run": "false"
  }
}
```

`date` 留空时，GitHub runner 会按 `TZ: Asia/Shanghai` 使用当天北京时间日期。

## 外部定时表

外部服务如果使用 UTC 时间，按下面配置；括号内是北京时间。GitHub workflow 内置的备用 `schedule` 也是同一张表。

| UTC cron | 北京时间 | Body inputs |
|---|---:|---|
| `7 12 * * *` | 20:07 | `"slot": "20", "attempt": "1"` |
| `12 12 * * *` | 20:12 | `"slot": "20", "attempt": "2"` |
| `17 12 * * *` | 20:17 | `"slot": "20", "attempt": "3"` |
| `25 13 * * *` | 21:25 | `"slot": "21", "attempt": "1"` |
| `30 13 * * *` | 21:30 | `"slot": "21", "attempt": "2"` |
| `35 13 * * *` | 21:35 | `"slot": "21", "attempt": "3"` |
| `5 14 * * *` | 22:05 | `"slot": "22", "attempt": "1"` |
| `10 14 * * *` | 22:10 | `"slot": "22", "attempt": "2"` |
| `15 14 * * *` | 22:15 | `"slot": "22", "attempt": "3"` |

时间依据：

- 20 点限时码常见在 20:05 左右开始被稳定博主补齐，所以从 20:07 开始查。
- 21 点限时码近期更常见在 21:23-21:38 左右出现，所以延后到 21:25/21:30/21:35。
- 22 点限时码通常在 22 点后发布，保留 22:05/22:10/22:15 三次检查。
- 某个 slot 一旦成功发送，后续同 slot 的 attempt 会通过 `.garden_code_state.json` 跳过，不再继续搜索和发送。

内容策略：

- 优先使用稳定更新的博主，如草莓熊崽、若水、jojomoonX、时光机无心等。
- 只提取官服/微信版本段落，过滤吱吱宝服、抖服、渠道服等非目标服区。
- 多个来源出现同一码时优先发送；单个稳定来源也可发送，但会在正文里标明佐证来源数量。

## 验证

先建一条 dry-run 测试任务，把 body 里的 `dry_run` 改成 `"true"`，确认 GitHub Actions 出现 `workflow_dispatch` 且运行成功。测试成功后再改回 `"false"`。

成功标准：

- GitHub Actions 出现 `workflow_dispatch` 运行。
- 运行分支是 `main`。
- 运行结论是 `success`。
- 正式任务的 `dry_run` 是 `"false"`。
- 手机推送正文里出现 `来源：云端 GitHub`。

## 旧 workflow

`garden-codes.yml` 是早期公开网页搜索方案，现在只保留手动触发，不再自动定时运行。自动推送以 `garden-xhs-cloud.yml` 为准。
