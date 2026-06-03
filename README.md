# 我的花园世界限时码推送

这个仓库用 GitHub Actions 每天 20:05 北京时间自动搜索《我的花园世界》限时码，并通过 Server 酱推送到手机。

## 使用步骤

1. 在 GitHub 新建一个仓库，公开或私有都可以。
2. 上传本仓库里的文件。
3. 进入 GitHub 仓库 `Settings -> Secrets and variables -> Actions -> New repository secret`。
4. 新增 secret：
   - Name: `SERVERCHAN_SEND_URL`
   - Secret: Server 酱 SendKey/AppKey 页面上的完整 API URL
5. 进入 `Actions -> Garden Codes`，点 `Run workflow` 手动测试一次。

## 时间

`.github/workflows/garden-codes.yml` 使用 UTC 时间：

```yaml
cron: "5 12 * * *"
```

对应北京时间每天 20:05。GitHub 定时任务偶尔会有几分钟延迟。

## 费用

公开仓库的标准 GitHub-hosted runner 免费。私有仓库也有 GitHub Free 额度；这个任务每天跑一次，通常远低于免费额度。
