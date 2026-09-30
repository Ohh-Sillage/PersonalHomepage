# 架构说明（ARCHITECTURE.md）

> 个人主页网站 yjgnet.cn 的系统架构文档。
> 配套阅读：[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md)（为什么这样设计）、
> [USAGE_GUIDE.md](USAGE_GUIDE.md)（怎么使用与维护）、
> [deploy/DEPLOY.md](deploy/DEPLOY.md)（从零部署手册）。

## 1. 系统总览

单人维护的 AI 方向个人主页：展示个人信息、技能、经历、项目与博客文章，
内置一个 AI 助手聊天窗口。设计目标是简单可靠、无前端构建链、低部署成本。

```text
                        互联网
                          │
                  ┌───────┴─────────────────────────┐
                  │  nginx (443, HTTPS 强制跳转)      │
                  │  · /static/*  → 静态文件直出       │
                  │  · /*         → 反向代理          │
                  └───────┬─────────────────────────┘
                          │ 127.0.0.1:8000（仅本机）
                  ┌───────┴─────────────────────────┐
                  │  uvicorn + FastAPI（systemd 托管）│
                  │  · 中间件：访问日志 / 安全事件      │
                  │  · 路由：pages / blog / chat      │
                  │  · 服务：博客解析 / LLM 助手       │
                  │  · 模板：Jinja2 → HTML            │
                  └───────┬─────────────────────────┘
                          │
         ┌────────────────┼───────────────────┐
         │                │                   │
    content/           logs/             LLM API（可选）
 site.yml + posts  app.log / security.log  OpenAI 兼容接口
```

## 2. 技术栈

| 层次 | 技术 | 说明 |
| --- | --- | --- |
| 反向代理 | nginx | HTTPS 终结、静态文件直出、SSE 免缓冲、真实 IP 注入 |
| Web 框架 | FastAPI | 路由、依赖注入、异步、自动校验 |
| ASGI 服务器 | uvicorn | 单 worker，仅监听 127.0.0.1:8000 |
| 模板引擎 | Jinja2 | 服务端渲染全部页面 |
| 前端 | 原生 CSS / JavaScript | 无框架、无打包、无构建步骤 |
| 内容 | YAML + Markdown | site.yml 站点内容；posts/*.md 博客 |
| 配置 | pydantic-settings | 读取 `.env`，环境变量可覆盖 |
| 进程管理 | systemd | 开机自启、崩溃自动重启 |
| HTTPS | Let's Encrypt / certbot | 自动续期 |
| 日志 | 标准库 logging | 按天轮转 + 自动清理（14 天） |

## 3. 目录结构

```text
PersonalHomepage/
├── app/                      # FastAPI 应用
│   ├── main.py               # 入口：应用创建、日志初始化、中间件挂载、lifespan
│   ├── config.py             # 配置（.env / 环境变量）
│   ├── logger.py             # 日志系统：app.log 与 security.log（轮转 + 自动清理）
│   ├── middleware.py         # 访问日志中间件、安全事件归类、真实 IP 解析
│   ├── site_content.py       # 加载 content/site.yml（mtime 缓存自动重载）
│   ├── templating.py         # Jinja2 实例与公共模板上下文
│   ├── routers/              # pages(主页) / blog(博客) / chat(AI 助手)
│   └── services/             # blog_service(文章解析) / llm_service(AI 回复)
├── templates/                # Jinja2 模板（base / index / blog / 404 + partials）
├── static/                   # CSS / JS / 简历 PDF / 图片（nginx 直出）
├── content/
│   ├── site.yml              # 全部个人信息（改内容只动这里）
│   └── posts/                # 博客文章（Markdown + front matter）
├── deploy/                   # nginx、systemd 配置、监控告警脚本与部署手册
├── logs/                     # 运行日志（已 gitignore）
│   └── server/               # sync.py logs 拉取的服务器日志副本
├── Test/                     # 临时脚本目录（tmp_*.py，用完即删）
├── sync.py                   # 一键同步 / 日志拉取工具
├── ARCHITECTURE.md           # 本文档
├── DESIGN_DECISIONS.md       # 设计决策记录
├── USAGE_GUIDE.md            # 使用指南
└── README.md
```

## 4. 请求生命周期

### 静态资源（CSS / JS / 图片 / 简历）

```text
浏览器 → nginx（location /static/，alias 到 /opt/homepage/static/）
       → 直接返回文件（expires 7d，不经过应用、不记应用日志）
```

### 动态页面（/、/blog、/blog/{slug}、404）

```text
浏览器 → nginx（注入 X-Real-IP / X-Forwarded-For）
       → uvicorn(127.0.0.1:8000)
       → 访问日志中间件（记录开始时间、解析真实 IP）
       → FastAPI 路由 → 读取 content/（site.yml 带 mtime 缓存）
       → Jinja2 渲染 HTML → 返回
       → 中间件收尾：写访问日志；4xx/5xx 或可疑路径额外写安全日志
```

### AI 助手（POST /api/chat，SSE 流式）

```text
浏览器(fetch/EventSource) → nginx（proxy_buffering off 保证流式）
       → chat 路由：三层用量防护（保护 API 费用）
          ① 分钟限流：每 IP 每分钟 ≤ CHAT_RATE_LIMIT（默认 10 次）
          ② 每日限额：每 IP 每日 ≤ CHAT_DAILY_LIMIT_PER_IP（默认 30 次，超限 429）
          ③ 全站预算：当日 token 估算 ≤ CHAT_DAILY_TOKEN_BUDGET（默认 20 万）
       → llm_service：有 LLM_API_KEY 走真实模型（max_tokens=LLM_MAX_TOKENS）；
          预算耗尽或无 Key 时降级预设知识库打字机流式（不产生费用）
       → 逐段推送 `data: {"delta": "..."}`，以 [DONE] 结束
       → 结束时写用量统计：logs/llm_usage.json + app.log "AI 用量" 行
```

## 5. 应用模块职责

| 模块 | 职责 | 关键点 |
| --- | --- | --- |
| `app/main.py` | 应用组装 | `setup_logging()` 最先执行；lifespan 记录启动/关闭锚点 |
| `app/logger.py` | 日志系统 | 按天轮转，`KEEP_DAYS=14` 自动删除过期文件 |
| `app/middleware.py` | 可观测性 | 每个请求一行访问日志；`get_client_ip()` 供限流与日志共用 |
| `app/site_content.py` | 内容加载 | mtime 变化才重读，改 site.yml 刷新页面即生效 |
| `app/routers/chat.py` | AI 接口 | 三层用量防护（分钟/每日/预算）、用量统计持久化、历史裁剪、异常记录 |
| `app/services/llm_service.py` | AI 回复 | 双模式；httpx 流式解析 SSE；max_tokens 上限与 token 估算 |

## 6. 内容体系

### 站点内容（content/site.yml）

单一内容源：姓名、职位、简介、邮箱、社交链接、技能、经历、项目、导航。
`site_content.py` 带 mtime 缓存——**修改后无需重启服务**，刷新页面即生效。

### 博客文章（content/posts/*.md）

```yaml
---
title: "文章标题"
date: 2026-09-01
tags: ["标签A"]
summary: "列表页摘要"
---
正文 Markdown……
```

渲染管线：python-frontmatter 解析元数据 → markdown 库渲染正文 →
pygments 代码高亮 → 注入模板。

## 7. 日志与安全监控体系

### 日志文件（应用侧，位于 `logs/`，服务器上为 `/opt/homepage/logs/`）

| 文件 | 内容 | 级别 |
| --- | --- | --- |
| `app.log` | 应用启动/关闭、全部访问行（方法/路径/状态/耗时/IP/UA）、AI 提问与用量、异常堆栈 | INFO+ |
| `security.log` | 4xx/5xx 响应、可疑路径探测、限流与每日限额拦截（完整时间线仍保留在 app.log） | WARNING+ |
| `llm_usage.json` | 当日 AI 用量（全站 token 估算 + 每 IP 次数/用量），跨天自动清零、重启不丢失 | 数据文件 |
| `monitor_state.json` | 监控告警冷却状态（server_monitor.py 维护） | 数据文件 |

### 轮转与清理（全自动，无需人工干预）

- 应用日志：每天零点轮转一次（`app.log.2026-09-11`），**自动删除 14 天前的文件**；
- nginx 日志（`/var/log/nginx/`）：Ubuntu 自带 logrotate 每周轮转、保留 14 份；
- systemd journal：应用输出同时进 journal，由 journald 自身按容量回收。

### 真实 IP 链路（排查攻击的关键）

```text
nginx: proxy_set_header X-Real-IP $remote_addr
中间件: get_client_ip() 优先 X-Real-IP → X-Forwarded-For 首项 → socket 地址
```

应用只监听 127.0.0.1，外部无法绕过 nginx 伪造该头；
限流与日志使用同一 IP 解析，保证两者一致。

### 安全事件识别

- 可疑路径探测：请求路径命中扫描特征（`.php`、`wp-`、`.env`、`.git`、`/admin`、`phpmyadmin` 等，本站均不存在）→ 仅记录，不拦截；
- 4xx/5xx：错误状态自动归类到 security.log；
- 限流拦截：`/api/chat` 超过阈值（默认 10 次/分钟/IP）；
- 每日限额拦截与预算降级：单 IP 超过每日次数上限返回 429；全站预算耗尽后
  自动降级预设知识库（当天不再产生任何 API 费用）。

### 服务器监控与邮件告警（主动发现）

```text
cron（/etc/cron.d/homepage-monitor，以 homepage 用户运行）
 ├─ check   每 5 分钟：服务 active / 健康检查 / 磁盘 / 内存
 │          异常 → 立即发告警邮件（同类问题按 ALERT_COOLDOWN_HOURS 冷却）
 │          恢复 → 自动补发「已恢复」邮件并复位状态
 └─ report  每周一 09:05：发送过去 7 天运行报告
             （系统状态 / 访问统计 / 安全事件 / AI 用量）
```

- 实现：`deploy/server_monitor.py`，纯标准库（smtplib / urllib / statvfs），零依赖；
- 配置：全部来自 `.env` 的 `ALERT_*`（开关 / SMTP / 收件人 / 阈值 / 冷却），
  每次执行时读取，改完即生效；
- 告警与报告由服务器主动发出，不依赖任何人打开网站——
  服务完全宕机时 check 同样能发现并邮件通知；
- 冷却状态持久化在 `logs/monitor_state.json`，防止故障期间反复轰炸邮箱。

## 8. 部署架构

```text
Windows 开发机 ── sync.py(paramiko/SFTP) ──► 146.56.223.180（腾讯云 Ubuntu 22.04）
                                              /opt/homepage（属主 homepage）
                                              systemd: homepage.service
                                              nginx: /etc/nginx/sites-available/yjgnet.cn
                                              certbot 定时续期
```

- 服务进程：`User=homepage`、`Restart=always`、`NoNewPrivileges=true`；
- 应用目录与日志目录属主均为 `homepage`，同步脚本临时借用属主后归还；
- 本地改动 → `python sync.py <模式>` → 内容免重启/代码自动重启 → 外网验证。

## 9. 安全设计汇总

| 项目 | 措施 |
| --- | --- |
| 传输安全 | HTTPS（Let's Encrypt），HTTP 301 强制跳转 |
| 信息暴露面 | `server_tokens off` 隐藏 nginx 版本；无登录、无数据库 |
| 网络隔离 | 应用仅监听 127.0.0.1，所有流量必经 nginx |
| 接口防护 | `/api/chat` 三层用量防护：分钟限流 + 每 IP 每日限额 + 全站 token 预算（超限降级，不再产生费用） |
| 主动监控 | cron 每 5 分钟巡检查服务/健康/磁盘/内存，异常邮件告警（含恢复通知）；每周一自动运行报告 |
| 密钥管理 | 全部配置集中于 `.env`（gitignore），服务器上 640 权限仅服务用户可读；代码零硬编码 |
| 输入约束 | 聊天消息长度 ≤2000、历史轮数裁剪、角色白名单 |
| 攻击发现 | 安全日志（扫描探测/错误响应/限流），支持 `python sync.py logs` 拉取分析 |
| 敏感文件 | `.env`、`.sync_config.json` 已被 gitignore，不进入仓库 |
