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
                  │  · 服务：博客解析 + assistant/ 模块│
                  │  · 模板：Jinja2 → HTML            │
                  └───────┬─────────────────────────┘
                          │
         ┌────────────────┼───────────────┬────────────────────┐
         │                │               │                    │
    content/           logs/          skills/            LLM API（可选）
 site.yml + posts  app.log/security  技能平台         多通道 OpenAI 兼容
                                     （SKILL.md）       （断路器 + 故障转移）
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
├── app/                      # FastAPI 应用（站点主体）
│   ├── main.py               # 入口：应用创建、日志初始化、中间件挂载、lifespan、AI 助手装配
│   ├── config.py             # 站点配置（.env / 环境变量；AI 配置在 assistant/config.py）
│   ├── logger.py             # 日志系统：app.log 与 security.log（轮转 + 自动清理）
│   ├── middleware.py         # 访问日志中间件、安全事件归类、真实 IP 解析
│   ├── site_content.py       # 加载 content/site.yml（mtime 缓存自动重载）
│   ├── templating.py         # Jinja2 实例与公共模板上下文
│   ├── routers/              # pages(主页) / blog(博客)
│   └── services/             # 内容服务：blog_service.py（文章解析）
├── assistant/                # AI 助手独立包（详见 assistant/ARCHITECTURE.md）
│   ├── config.py             # AIConfig：自读 .env，可被宿主覆盖
│   ├── adapters.py           # 宿主适配：site_provider / client_ip / security_logger
│   ├── health/               # 子系统：健康检测（断路器 + 主动探针，可单独移植）
│   ├── harness/              # 子系统：技能平台基座（零业务知识，可单独移植）
│   ├── memory/               # 子系统：记忆（协议 + Noop 实现）
│   ├── llm/                  # 子系统：对话核心（流式生成 + 预设知识库）
│   └── chat/                 # 装配层：POST /api/chat + 限流限额用量
├── skills/                   # 技能平台（每个技能一个目录）
│   └── send-resume/          # 简历邮件技能：SKILL.md + scripts/send_resume.py + handler.py
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

实现位于顶层独立包 `assistant/`（与 app/ 平级，子系统可插拔）；完整的全链路数据流
（含 memory 接入点、降级细节与移植手册）见
[assistant/ARCHITECTURE.md](assistant/ARCHITECTURE.md) 第 4 节。摘要：

```text
浏览器(fetch/EventSource) → nginx（proxy_buffering off 保证流式）
       → assistant/chat：三层用量防护（分钟限流 / 每日限额 / 全站 token 预算）
       → assistant/harness：技能编排（正则初筛 → L2 参数约束 → L1 白名单执行 → L3 审计）
       → assistant/llm：多通道故障转移流式（断路器快速失败 → 备用通道 → 降级预设库）
       → 逐段推送 `data: {"delta": "..."}`，以 [DONE] 结束
       → 收尾：memory.remember + 用量落盘 logs/llm_usage.json + app.log "AI 用量" 行
```

> 故障转移：每通道独立断路器——连续失败 3 次 → OPEN 快速失败（毫秒级返回、
> 不发真实请求）；冷却 90s 后放行后台健康探针（60s 间隔，max_tokens=1），
> 探针成功自动恢复。CLOSED 通道靠真实请求被动感知，不发额外探针（省 token）。
> 实时状态见 `GET /api/health` 的 `llm` 字段。

## 5. 应用模块职责

| 模块 | 职责 | 关键点 |
| --- | --- | --- |
| `app/main.py` | 应用组装 | `setup_logging()` 最先执行；lifespan 记录启动/关闭锚点、装配 AI 助手（`AIAssistant`）并托管探针生命周期 |
| `app/logger.py` | 日志系统 | 按天轮转，`KEEP_DAYS=14` 自动删除过期文件 |
| `app/middleware.py` | 可观测性 | 每个请求一行访问日志；`get_client_ip()` 供限流与日志共用 |
| `app/site_content.py` | 内容加载 | mtime 变化才重读，改 site.yml 刷新页面即生效 |
| `assistant/chat/router.py` | AI 接口 | 三层用量防护（分钟/每日/预算）、技能编排调用（线程池）、用量统计持久化、历史裁剪、异常记录、记忆接入点 |
| `assistant/llm/` | AI 回复 | 双模式；多通道故障转移流式（断路器钩子）；技能结果块/记忆片段注入提示词；token 估算 |
| `assistant/health/` | 健康检测 | 断路器三态机（失败阈值 / 冷却 / 半开）；后台探针只探 OPEN 通道；`/api/health` 快照（可单独移植） |
| `assistant/harness/` | 技能平台基座 | SKILL.md 解析（mtime 缓存）；渐进式披露索引；白名单加载（executor/handler）；触发编排与审计（零业务知识） |
| `assistant/memory/` | 记忆（骨架） | MemoryStore 协议（recall/remember/clear）+ NoopMemory；链路接入点已就绪 |
| `assistant/__init__.py` | 装配入口 | AIAssistant：router / start / stop / health_snapshot；默认实现开箱即用 |

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

## 7. 技能平台（skills/，对齐 week13 harness 模式）

技能平台基座实现在 [assistant/harness/](assistant/ARCHITECTURE.md)（零业务知识、可单独移植），
技能内容在 `skills/` 目录；本节为站点视角摘要，子系统边界与移植手册见
[assistant/ARCHITECTURE.md](assistant/ARCHITECTURE.md)。

### 技能即目录

```text
skills/<技能名>/
├── SKILL.md          # frontmatter：name / description / trigger / entry
├── scripts/          # 执行脚本（基座白名单加载）
└── handler.py        # 可选：detect() 触发匹配 + execute() 执行（技能自带话术）
```

SKILL.md 的 frontmatter 声明技能名、何时触发、入口脚本；正文是完整定义
（触发场景、执行流程、约束、输出契约、自检清单），触发后按需加载。

### 执行链路（确定性触发 + LLM 转述）

```text
访客消息 → 正则初筛（零 token，如“简历 + 邮箱”模式）
        → L2 参数约束（邮箱格式 / 每 IP 每日限额 / 附件路径固定，杜绝注入）
        → L1 白名单加载 skills/<技能名>/scripts/<entry> 执行（每次重载，改动免重启）
        → 结构化结果（sent / need_email / blocked / error）
        → LLM 用自然语言如实转达（禁止编造）；无 LLM 时转预设话术直接回复
        → L3 审计：成功明细写 app.log，拦截与异常写 security.log
```

设计取舍详见 [assistant/DESIGN_DECISIONS.md](assistant/DESIGN_DECISIONS.md) 的 A4
（为何不用 Function Calling）；基座零业务知识的设计见 A7。

### 渐进式披露（控制 token）

| 层级 | 时机 | 内容 |
| --- | --- | --- |
| 常驻层 | 每次对话 | 技能索引一行一项（<200 token），注入系统提示词 |
| 触发层 | 技能被触发 | 执行结果与回复要求注入提示词 |
| 执行层 | 脚本运行时 | 按 mtime 缓存重载，`sync.py skills` 免重启生效 |

### 现有技能

| 技能 | 功能 | 触发条件 |
| --- | --- | --- |
| send-resume | 把简历 PDF 发到访客邮箱（纯 Python smtplib，复用 `ALERT_SMTP_*`） | 消息含“简历/resume/cv/履历”且提供邮箱；或追问邮箱后直接回复邮箱 |

## 8. 日志与安全监控体系

### 日志文件（应用侧，位于 `logs/`，服务器上为 `/opt/homepage/logs/`）

| 文件 | 内容 | 级别 |
| --- | --- | --- |
| `app.log` | 应用启动/关闭、全部访问行（方法/路径/状态/耗时/IP/UA）、AI 提问与用量、异常堆栈 | INFO+ |
| `security.log` | 4xx/5xx 响应、可疑路径探测、限流与每日限额拦截（完整时间线仍保留在 app.log） | WARNING+ |
| `llm_usage.json` | 当日 AI 用量（全站 token 估算 + 每 IP 次数/用量），跨天自动清零、重启不丢失 | 数据文件 |
| `resume_usage.json` | 当日简历邮件发送计数（每 IP），跨天自动清零、重启不丢失 | 数据文件 |
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
  自动降级预设知识库（当天不再产生任何 API 费用）；
- 简历邮件限额拦截：同一 IP 当日发送简历邮件超过 `RESUME_DAILY_LIMIT_PER_IP`
  （默认 3 封），拦截事件写入 security.log；技能执行明细（含收件邮箱）在 app.log。

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

## 9. 部署架构

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

## 10. 安全设计汇总

| 项目 | 措施 |
| --- | --- |
| 传输安全 | HTTPS（Let's Encrypt），HTTP 301 强制跳转 |
| 信息暴露面 | `server_tokens off` 隐藏 nginx 版本；无登录、无数据库 |
| 网络隔离 | 应用仅监听 127.0.0.1，所有流量必经 nginx |
| 接口防护 | `/api/chat` 三层用量防护：分钟限流 + 每 IP 每日限额 + 全站 token 预算（超限降级，不再产生费用） |
| 技能防护 | 三层防护：L1 执行脚本白名单（仅技能目录内）、L2 参数约束（邮箱校验 / 每日限额 / 固定附件防路径注入）、L3 全链路审计 |
| LLM 可用性 | 多通道断路器 + 后台探针：故障通道快速失败（不发请求不产生费用），恢复后自动切回 |
| 主动监控 | cron 每 5 分钟巡检查服务/健康/磁盘/内存，异常邮件告警（含恢复通知）；每周一自动运行报告 |
| 密钥管理 | 全部配置集中于 `.env`（gitignore），服务器上 640 权限仅服务用户可读；代码零硬编码 |
| 输入约束 | 聊天消息长度 ≤2000、历史轮数裁剪、角色白名单 |
| 攻击发现 | 安全日志（扫描探测/错误响应/限流），支持 `python sync.py logs` 拉取分析 |
| 敏感文件 | `.env`、`.sync_config.json` 已被 gitignore，不进入仓库 |
