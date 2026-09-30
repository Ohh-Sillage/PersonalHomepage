# 使用指南（USAGE_GUIDE.md）

> 本指南面向站点维护者（就是你自己）：怎么改内容、怎么发布、怎么看日志、出问题怎么办。
> 配套阅读：[ARCHITECTURE.md](ARCHITECTURE.md)（系统怎么跑）、
> [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md)（为什么这样设计）、
> [deploy/DEPLOY.md](deploy/DEPLOY.md)（从零部署手册）。
>
> 所有命令在项目根目录、`homepage` conda 环境下执行。

---

## 1. 快速上手

### 1.1 本地运行

```bat
call conda activate homepage
uvicorn app.main:app --reload --port 8000
```

浏览器访问 http://127.0.0.1:8000。

启动后本地会生成 `logs/app.log` 与 `logs/security.log`；
`--reload` 模式下改 Python 代码自动重启，改 content/ 下的内容刷新页面即生效。

### 1.2 控制台日志速读

启动时会看到两类锚点日志，方便确认版本与配置状态：

```text
2026-09-11 15:46:01 INFO [access] "GET /" 200 87.5ms ip=127.0.0.1 ua="Mozilla/5.0 ..."
2026-09-11 15:46:01 INFO [app] 应用启动: https://yjgnet.cn（LLM: 未配置，使用预设知识库）
```

配置 `LLM_API_KEY` 后该行会显示「LLM: 已配置」，可用来确认真实模型是否生效。

## 2. 日常内容维护

### 2.1 常见维护对照表

| 想改什么 | 改哪里 | 是否需重启 |
| --- | --- | --- |
| 姓名、职位、简介、邮箱、社交链接 | `content/site.yml` | 否，刷新即生效 |
| 技能、工作经历、项目作品 | `content/site.yml` | 否 |
| 导航菜单 | `content/site.yml`（nav 段） | 否 |
| 发新博客文章 | `content/posts/` 新建 `.md` | 否 |
| 更换简历 PDF | 覆盖 `static/files/resume.pdf` | 否（需同步 static） |
| 更换项目截图 | 图片放 `static/img/`，site.yml 填 `/static/img/xxx.png` | 否（需同步 static） |
| 页面结构、样式、交互 | `templates/`、`static/css`、`static/js` | 本地改；线上需同步 |

### 2.2 发一篇博客

在 `content/posts/` 新建 Markdown 文件（文件名即 URL 的 slug）：

```yaml
---
title: "文章标题"
date: 2026-09-01
tags: ["标签A"]
summary: "列表页展示的摘要。"
---
正文 Markdown 内容……
```

同步 `python sync.py content` 后，线上 https://yjgnet.cn/blog 立即出现（无需重启）。

### 2.3 重要规则（踩过坑的）

1. **改了 `static/` 下被 `?v=N` 引用的文件（style.css / main.js），
   必须同步递增 `templates/base.html` 里的版本号**，否则浏览器 7 天缓存
   不回源，线上看不到改动；
2. **模板中插入自产生 HTML（如内联 SVG 图标）必须用块赋值 + `|safe`**，
   否则 Jinja2 自动转义会把属性引号转成 `&#34;` 导致渲染失败；
3. `.env` 与 `deploy/.sync_config.json` 永不提交仓库（已在 .gitignore）；
4. **给组件设了 `display` 后要补 `[hidden]` 规则**：如 `.chat-panel{display:flex}`
   会覆盖浏览器默认的 `[hidden]{display:none}`，导致"点 X 关不掉面板"。
   凡可关闭/隐藏的组件，必须在其样式旁补一条 `.组件[hidden]{display:none}`
   （AI 助手面板已按此修复）。

## 3. 发布上线

### 3.1 一键同步（sync.py）

```bat
python sync.py content     rem 只同步文章/文案，秒级，无需重启
python sync.py static      rem 同步图片/简历等静态资源，无需重启
python sync.py app         rem 同步后端代码，自动重启服务
python sync.py templates   rem 同步页面模板，自动重启服务
python sync.py deploy      rem 同步 nginx/systemd 等部署配置
python sync.py env         rem 同步 .env 配置到服务器（含密钥，显式执行才会上传）
python sync.py all         rem 全量同步（日常发布最常用）
python sync.py logs        rem ★ 反向操作：把服务器日志拉回本地
```

### 3.2 典型发布流程

```bat
rem 1. 本地改完、刷新 127.0.0.1:8000 自测
rem 2. 全量同步
python sync.py all
rem 3. 外网验证（绕过本机代理）
curl --noproxy "*" --resolve yjgnet.cn:443:146.56.223.180 -sI https://yjgnet.cn
```

## 4. 日志使用指南

### 4.1 日志在哪

| 位置 | 路径 | 说明 |
| --- | --- | --- |
| 本地开发 | `logs/app.log`、`logs/security.log` | 本地运行时产生 |
| 服务器 | `/opt/homepage/logs/`（属主 homepage） | 线上运行日志 |
| 本地查看线上 | `logs/server/`（`sync.py logs` 拉取的副本） | 推荐排查方式 |
| 用量 / 监控状态 | `logs/llm_usage.json`、`logs/monitor_state.json` | 自动生成（AI 每日用量、告警冷却），删除即重置 |
| nginx | 服务器 `/var/log/nginx/yjgnet.access.log` / `.error.log` | 系统 logrotate 管理 |

### 4.2 拉取线上日志

```bat
python sync.py logs
```

拉完后直接用编辑器打开 `logs/server/app.log` 或 `security.log` 分析。
该命令只读不改（临时借用属主，结束自动归还），可随时执行。

### 4.3 日志格式解读

**访问日志（app.log 中 `[access]` 行）**——每个动态请求一行：

```text
2026-09-11 15:48:19 INFO [access] "GET /" 200 87.5ms ip=218.21.116.74 ua="curl/8.13.0"
                              方法  路径   状态  耗时   真实访客 IP      浏览器标识
```

**安全日志（security.log）**——四类事件：

```text
WARNING [security] 可疑路径探测: ip=1.2.3.4 GET /wp-login.php ua="..."
WARNING [security] 404 响应: ip=1.2.3.4 GET /no-such-page
WARNING [security] 限流拦截: ip=1.2.3.4 超过 10 次/分钟
ERROR   [security] 服务端异常: ip=1.2.3.4 GET /blog/xxx     # 附带堆栈在 app.log
```

### 4.4 排查场景速查

| 场景 | 看哪里 | 怎么找 |
| --- | --- | --- |
| 网站整体打不开 | `systemctl status homepage`、`app.log` 尾部 | 有无"应用关闭"、异常堆栈 |
| 某个页面 500 | `app.log` 搜 `Traceback` / `ERROR` | 按时间定位请求与堆栈 |
| 某访客反馈出错 | `app.log` 搜其 IP | 查看该 IP 的完整请求时间线 |
| 怀疑被扫描/攻击 | `security.log` | 搜 `可疑路径探测`、统计高频繁 IP |
| AI 助手不回复 | `app.log` 搜 `AI 提问` / `AI 回复失败` | 结合 ip 与时间定位 |
| AI 提示"提问次数已用完" | `security.log` 搜 `每日限额拦截` | 每 IP 每日限额（默认 30 次），次日零点自动清零 |
| AI 回答变成固定模板 | `app.log` 搜 `预算耗尽` | 全站 token 预算用尽后自动降级预设知识库（护钱包机制） |
| 想看 AI 花了多少 token | `logs/llm_usage.json`、`app.log` 搜 `AI 用量` | 每次提问的估算输入/输出与当日累计 |
| 响应变慢 | `app.log` 访问行的耗时字段 | 过滤 `ms` 前数值大的行 |

### 4.5 日志保留与自动清理

- **应用日志：保留 14 天**。每天零点自动轮转为 `app.log.2026-09-11`
  形式，14 天前的文件被自动删除——**无需任何人工操作**；
- nginx 日志：Ubuntu 自带 logrotate 每周轮转、保留 14 份；
- 想调整保留天数：改 `app/logger.py` 中的 `KEEP_DAYS` 并 `python sync.py app`。

## 5. 安全监控与应对

### 5.1 当前已启用

| 措施 | 状态 |
| --- | --- |
| HTTPS 强制跳转（HTTP 301） | 已启用 |
| nginx 版本号隐藏（`server_tokens off`） | 已启用 |
| AI 接口按真实 IP 限流（默认 10 次/分钟） | 已启用，可在 `.env` 调整 |
| AI 每日限额（每 IP 30 次/日）与全站 token 预算（超限降级，不再产生费用） | 已启用，可在 `.env` 调整 |
| 服务器自动巡检（每 5 分钟）+ 异常邮件告警 + 周一运行报告 | 已启用（cron + `deploy/server_monitor.py`） |
| 扫描探测 / 错误响应记录到 security.log | 已启用 |
| 应用仅监听 127.0.0.1，无法绕过 nginx | 已启用 |

### 5.2 发现可疑行为怎么办

1. `python sync.py logs` 拉取日志；
2. 看 `security.log`：统计可疑 IP 出现频次与时间范围；
3. 若只是互联网背景噪音（每日零星扫描很常见），**无需处理**，已自动记录；
4. 若出现持续高频攻击：可在服务器上用 `ufw deny from <IP>` 临时封禁，
   或在 nginx 层配置限连（当前量级一般用不到）。

### 5.3 服务器监控与邮件告警

服务器上通过 cron 每 5 分钟执行一次 `deploy/server_monitor.py check`：

| 检查项 | 告警条件 |
| --- | --- |
| 应用服务 | `homepage.service` 不是 active |
| 网站健康 | `http://127.0.0.1:8000/api/health` 无响应 |
| 磁盘 | 根分区使用率 ≥ `ALERT_DISK_THRESHOLD`（默认 85%） |
| 内存 | 使用率 ≥ `ALERT_MEM_THRESHOLD`（默认 90%） |

- 出现异常 → 立即发告警邮件；同类问题 `ALERT_COOLDOWN_HOURS`（默认 6）小时内
  不重复发；问题恢复 → 自动补发一封「已恢复」邮件；
- 每周一 09:05 自动发送过去 7 天的运行报告（系统状态 / 访问统计 / 安全事件 / AI 用量）；
- 所有参数都在 `.env` 的 `ALERT_*`（见第 7 节），改完下次执行即生效；
- 收到告警邮件后：先 `python sync.py logs` 拉日志分析，或 SSH 执行
  `sudo systemctl status homepage` / `tail /opt/homepage/logs/app.log`。

手动验证监控与邮箱（服务器上执行）：

```bash
sudo -u homepage python3 /opt/homepage/deploy/server_monitor.py test    # 发一封测试邮件
sudo -u homepage python3 /opt/homepage/deploy/server_monitor.py check   # 立即巡检（正常则打印"检查通过"）
sudo -u homepage python3 /opt/homepage/deploy/server_monitor.py report  # 立即发一份周报
```

## 6. 故障排查 Q&A

**Q1：线上页面是旧样式/旧文案？**
→ 先强刷（Ctrl+F5）；仍不行检查是否忘了递增 `?v=N` 版本号，再 `sync.py all`。

**Q2：`sync.py` 报 chown 或权限错误？**
→ 检查 `deploy/.sync_config.json` 中密码是否正确、用户是否有 sudo 权限。

**Q3：日志文件没生成？**
→ 确认进程工作目录为项目根目录；`logger.py` 在目录不可写时会降级为仅控制台，
控制台仍能看到日志。

**Q4：`sync.py logs` 提示"服务器上还没有日志目录"？**
→ 应用尚未在服务器上产生日志（如刚部署未收到请求），发起一次访问后再拉。

**Q5：如何确认线上跑的是最新代码？**
→ `app.log` 中 `应用启动` 行的时间应接近你最后一次 `sync.py all` 的时间。

**Q6：接口被限流了怎么自查？**
→ `security.log` 搜 `限流拦截`，日志中的 IP 即限流所用 IP（两者同源）；
本地开发调高阈值：`.env` 里设 `CHAT_RATE_LIMIT=100`。

**Q7：访客反馈"今天的提问次数已用完"？**
→ 每 IP 每日限额（默认 30 次）生效，次日零点自动清零。确需提高：改 `.env` 的
`CHAT_DAILY_LIMIT_PER_IP` 后执行 `python sync.py env`（同步配置并自动重启）。

**Q8：AI 回答变成固定模板、没有走真实模型？**
→ 当日全站 token 预算（默认 20 万）已耗尽，系统自动降级预设知识库以避免继续
产生 API 费用，次日零点自动恢复。预算大小可改 `CHAT_DAILY_TOKEN_BUDGET`。

**Q9：没收到告警/周报邮件？**
→ 服务器上手动发测试邮件：
`sudo -u homepage python3 /opt/homepage/deploy/server_monitor.py test`；
若提示"邮件未启用或配置不完整"，检查 `.env` 的 `ALERT_EMAIL_ENABLED` /
`ALERT_SMTP_USER` / `ALERT_SMTP_PASSWORD`（邮箱 SMTP 授权码，不是登录密码）。

## 7. 环境变量速查（.env）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SITE_URL` | `https://yjgnet.cn` | 站点地址（启动日志中展示） |
| `LLM_API_KEY` | 空 | 留空 = 预设知识库模式；填入即启用真实模型 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | `deepseek-flash` | 模型名（DeepSeek V4.1 Flash） |
| `LLM_MAX_TOKENS` | `500` | 单次回复生成上限（token） |
| `CHAT_RATE_LIMIT` | `10` | 每 IP 每分钟最大聊天请求数 |
| `CHAT_DAILY_LIMIT_PER_IP` | `30` | 每 IP 每日最大提问次数（超限返回 429） |
| `CHAT_DAILY_TOKEN_BUDGET` | `200000` | 全站每日 token 预算（估算），超限降级预设知识库 |
| `ALERT_EMAIL_ENABLED` | `true` | 告警邮件总开关（false / 留空 = 关闭） |
| `ALERT_SMTP_HOST` / `ALERT_SMTP_PORT` | `smtp.qq.com` / `465` | 发信 SMTP（SSL） |
| `ALERT_SMTP_USER` | — | 发信邮箱账号 |
| `ALERT_SMTP_PASSWORD` | — | 邮箱 SMTP 授权码（不是登录密码） |
| `ALERT_EMAIL_TO` | 同发件账号 | 告警 / 报告收件地址 |
| `ALERT_COOLDOWN_HOURS` | `6` | 同类告警冷却时长（小时） |
| `ALERT_DISK_THRESHOLD` / `ALERT_MEM_THRESHOLD` | `85` / `90` | 磁盘 / 内存告警阈值（%） |

修改配置的推荐流程：本地改 `.env` 后执行 `python sync.py env`（同步到服务器并自动
重启；`.env` 含密钥，不会随 `sync.py all` 自动上传），也可 SSH 直接编辑
`/opt/homepage/.env`。仅改 `ALERT_*` 无需重启（监控脚本每次执行时读取）。

## 8. 常见运维命令（服务器上）

```bash
sudo systemctl status homepage       # 查看应用状态
sudo systemctl restart homepage      # 重启应用
sudo journalctl -u homepage -n 50    # 看最近 50 行输出
sudo nginx -t && sudo systemctl reload nginx   # 检查并重载 nginx
sudo tail -f /var/log/nginx/yjgnet.error.log   # 实时看 nginx 错误
cat /etc/cron.d/homepage-monitor     # 查看监控定时任务
sudo -u homepage python3 /opt/homepage/deploy/server_monitor.py check   # 手动巡检一次
sudo -u homepage python3 /opt/homepage/deploy/server_monitor.py test    # 发测试告警邮件
```

> 说明：应用日志同时会进 journal，但**排查请优先看 `logs/` 下的文件日志**
> （格式统一、含真实 IP 与耗时，且保留 14 天）。
