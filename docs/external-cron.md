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
| `10 12 * * *` | 20:10 | `"slot": "20", "attempt": "1"` |
| `15 12 * * *` | 20:15 | `"slot": "20", "attempt": "2"` |
| `20 12 * * *` | 20:20 | `"slot": "20", "attempt": "3"` |
| `10 13 * * *` | 21:10 | `"slot": "21", "attempt": "1"` |
| `15 13 * * *` | 21:15 | `"slot": "21", "attempt": "2"` |
| `20 13 * * *` | 21:20 | `"slot": "21", "attempt": "3"` |
| `10 14 * * *` | 22:10 | `"slot": "22", "attempt": "1"` |
| `15 14 * * *` | 22:15 | `"slot": "22", "attempt": "2"` |
| `20 14 * * *` | 22:20 | `"slot": "22", "attempt": "3"` |

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
