# 个人主页网站（yjgnet.cn）

AI 方向的个人主页：深色单页风格（布局参考 brittanychiang.com），
包含个人展示、技能、工作经历、项目作品、博客文章、简历下载与 AI 助手聊天。
技术栈：FastAPI + Jinja2 服务端渲染 + 原生 CSS/JS，无前端构建链。

## 目录结构

```
PersonalHomepage/
├── app/                  # FastAPI 应用
│   ├── main.py           # 入口：应用创建、日志初始化、中间件挂载
│   ├── config.py         # 配置（从 .env 读取）
│   ├── logger.py         # 日志系统（按天轮转 + 自动保留 14 天）
│   ├── middleware.py     # 访问日志中间件、安全事件归类、真实 IP 解析
│   ├── site_content.py   # 加载 content/site.yml（带自动重载）
│   ├── routers/          # pages / blog / chat 路由
│   └── services/         # 博客解析、AI 助手回复
├── templates/            # Jinja2 模板（base / index / blog / 404 + partials）
├── static/               # CSS / JS / 简历 PDF / 图片
├── content/
│   ├── site.yml          # 全部个人信息（改内容只动这里）
│   └── posts/            # 博客文章（Markdown + front matter）
├── deploy/               # nginx、systemd 配置、监控告警脚本与部署手册
├── logs/                 # 运行日志与用量/监控状态（gitignore；server/ 为拉取的线上日志）
├── ARCHITECTURE.md       # 架构说明
├── DESIGN_DECISIONS.md   # 设计决策记录
├── USAGE_GUIDE.md        # 使用与维护指南
└── requirements.txt
```

## 本地开发

使用独立 conda 环境 `homepage`：

```bat
conda create -n homepage python=3.12 -y
call conda activate homepage
pip install -r requirements.txt

rem 启动开发服务器（修改 Python 代码自动重载）
uvicorn app.main:app --reload --port 8000
```

浏览器访问 http://127.0.0.1:8000

> content/site.yml 与博客文章带 mtime 自动重载，改完刷新页面即生效，无需重启。

## 内容维护指南

| 想改什么 | 改哪里 |
| --- | --- |
| 姓名、职位、简介、邮箱、社交链接 | `content/site.yml` |
| 技能、工作经历、项目作品 | `content/site.yml` |
| 发新博客文章 | 在 `content/posts/` 新建 `.md`（含标题/日期/标签/摘要的 front matter） |
| 更换简历 | 用你的 PDF 覆盖 `static/files/resume.pdf` |
| 更换项目截图 | 图片放入 `static/img/`，在 `site.yml` 对应项目的 `image` 字段填 `/static/img/xxx.png` |

文章 front matter 示例：

```yaml
---
title: "文章标题"
date: 2026-09-01
tags: ["标签A", "标签B"]
summary: "列表页展示的摘要。"
---
正文 Markdown 内容……
```

## AI 助手

- 默认（未配置 Key）：基于 `site.yml` 的预设知识库回答，带打字机流式效果；
- 配置 `.env` 中 `LLM_API_KEY` 后：自动切换为 OpenAI 兼容接口的真实模型
  （当前线上为 DeepSeek `deepseek-flash`），前端零改动；
- 内置三层用量防护（防 token 恶意消耗）：每 IP 每分钟限流、每 IP 每日限额、
  全站每日 token 预算（超限自动降级预设知识库）；单次回复上限 `LLM_MAX_TOKENS`，
  用量统计见 `logs/llm_usage.json`——均可在 `.env` 调整。

## 服务器监控

- 每 5 分钟自动巡检（服务/健康/磁盘/内存），异常立即发邮件告警（含恢复通知）；
- 每周一自动发送 7 天运行报告（访问统计 / 安全事件 / AI 用量）；
- 实现在 `deploy/server_monitor.py`（纯标准库），SMTP 等配置在 `.env` 的 `ALERT_*`。

## 部署

线上地址：https://yjgnet.cn（服务器 146.56.223.180，见 [deploy/DEPLOY.md](deploy/DEPLOY.md)：Ubuntu + nginx + systemd + Let's Encrypt）。

### 本地改完后如何快速同步到服务器

在项目根目录执行一键同步工具（配置见 `deploy/.sync_config.json`）：

```bat
python sync.py content    rem 只同步文章/文案，无需重启，秒级生效
python sync.py static     rem 同步图片/简历等静态资源
python sync.py app        rem 同步后端代码，自动重启服务
python sync.py env        rem 同步 .env 配置到服务器（含密钥，显式执行才会上传）
python sync.py all        rem 全量同步
python sync.py logs       rem 拉取服务器日志到本地 logs/server/（排查问题用）
```

## 运行日志

- `logs/app.log`：启动/关闭、每个请求（状态码 / 耗时 / 真实 IP / UA）、AI 提问与用量、异常堆栈；
- `logs/security.log`：可疑扫描探测、4xx/5xx、限流与每日限额拦截等安全事件；
- `logs/llm_usage.json` / `logs/monitor_state.json`：AI 每日用量、告警冷却状态（自动维护）；
- 按天自动轮转，**自动保留最近 14 天**（无需人工清理）。

## 文档

| 文档 | 内容 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构：请求链路、模块职责、日志与安全体系 |
| [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | 设计决策：关键选择的原因与备选方案 |
| [USAGE_GUIDE.md](USAGE_GUIDE.md) | 使用指南：内容维护、发布流程、日志排查手册 |
| [deploy/DEPLOY.md](deploy/DEPLOY.md) | 从零部署手册（nginx / systemd / HTTPS） |

## 接口

| 路径 | 说明 |
| --- | --- |
| `GET /` | 主页（单页滚动） |
| `GET /blog` | 文章列表 |
| `GET /blog/{slug}` | 文章详情 |
| `POST /api/chat` | AI 助手（SSE 流式，三层用量防护） |
| `GET /api/health` | 健康检查 |
