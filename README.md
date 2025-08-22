# llm-daily-tracker
A powerful tool for developers, researchers, and power users to log, query, and gain insights from their conversations with ChatGPT, Claude, Gemini, and other LLMs. Transform scattered chats into structured data.

自动追踪大模型（LLM）资讯 / 官方博客 / 论文 ，并在 GitHub Actions 中每日生成一份 Markdown 日报。

- 输出位置：`docs/daily/YYYY-MM-DD.md`，最新索引：`docs/index.md`
- 定时：每天 09:00（北京时区），可在 `.github/workflows/daily.yml` 修改
- 数据源：`config.yaml` 中维护
- 技术栈：Python + GitHub Actions

## 快速开始
1. 新建仓库（或 fork），把本仓库文件复制进去。
2. 确认仓库的 Actions 权限允许 `contents: write`（默认已开）。
3. 修改 `config.yaml`（可选）：增删订阅源、关键词、时区等。
4. 手动触发一次：GitHub → Actions → LLM Daily Tracker → Run workflow。
5. 查看输出：`docs/daily/` 下的今日文件，主页 `docs/index.md`。

## 自定义
- 时区/时间窗口：`timezone`、`since_hours`
- 每源条数：`max_items.per_feed`
- arXiv 关键词：`arxiv` 下的 `query`，支持布尔与分类过滤

## 说明
- RSS 失败会在日志中提示并跳过，不阻塞整体执行
- `data/state.json` 用于去重和计算榜单变动
- 若需推送到 Notion/Slack/飞书，可在 `main.py` 末尾加入对应 API 调用

## 许可证
MIT
