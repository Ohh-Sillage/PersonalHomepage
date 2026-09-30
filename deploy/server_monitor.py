"""服务器监控：紧急异常告警 + 每周运行报告（cron 定时执行）。

用法（服务器上，任意 python3 均可，无第三方依赖）：
    python3 server_monitor.py check     # 每 5 分钟：检查服务/健康/磁盘/内存，异常发邮件
    python3 server_monitor.py report    # 每周一：发送过去 7 天的运行报告
    python3 server_monitor.py test      # 手动：发送一封测试邮件验证 SMTP 配置

配置：读取 .env 中的 ALERT_* 项（见项目根目录 .env.example 的说明）。
"""

import json
import os
import re
import smtplib
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # /opt/homepage
ENV_FILE = BASE / ".env"
LOG_DIR = BASE / "logs"
STATE_FILE = LOG_DIR / "monitor_state.json"

SERVICE = "homepage"                       # systemd 服务名
HEALTH_URL = "http://127.0.0.1:8000/api/health"
REPORT_DAYS = 7                            # 报告统计窗口（天）

# 固定检查项（key, 邮件标题）
CHECKS = (
    ("service", "应用服务已停止"),
    ("http", "网站健康检查失败"),
    ("disk", "磁盘空间不足"),
    ("mem", "内存使用率过高"),
)


def load_env() -> dict:
    """解析 .env 为字典（不依赖第三方库）。"""
    conf: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            conf[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return conf


def load_mail_config(env: dict) -> dict | None:
    """从环境配置中提取邮件参数；未启用/不完整时返回 None。"""
    enabled = env.get("ALERT_EMAIL_ENABLED", "").lower() in ("1", "true", "yes", "on")
    user = env.get("ALERT_SMTP_USER", "")
    password = env.get("ALERT_SMTP_PASSWORD", "")
    if not (enabled and user and password):
        return None
    return {
        "host": env.get("ALERT_SMTP_HOST", "smtp.qq.com"),
        "port": int(env.get("ALERT_SMTP_PORT", "465") or 465),
        "user": user,
        "password": password,
        "to": env.get("ALERT_EMAIL_TO", "") or user,
        "cooldown": int(env.get("ALERT_COOLDOWN_HOURS", "6") or 6) * 3600,
        "disk_th": float(env.get("ALERT_DISK_THRESHOLD", "85") or 85),
        "mem_th": float(env.get("ALERT_MEM_THRESHOLD", "90") or 90),
    }


def send_mail(cfg: dict, subject: str, body: str) -> None:
    """SSL 发送纯文本邮件；失败打印错误但不抛出（避免影响 cron）。"""
    msg = EmailMessage()
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    msg["Subject"] = f"[yjgnet.cn] {subject}"
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20) as server:
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
        print(f"[{now_str()}] 邮件已发送: {subject}")
    except Exception as exc:  # noqa: BLE001 - cron 场景下只记录不中断
        print(f"[{now_str()}] 邮件发送失败: {exc}", file=sys.stderr)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 系统检查

def service_active() -> bool:
    try:
        out = subprocess.run(
            ["systemctl", "is-active", SERVICE],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() == "active"
    except Exception:  # noqa: BLE001
        return False


def http_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def disk_stat() -> tuple[float, str]:
    st = os.statvfs("/")
    used_pct = round((1 - st.f_bavail / st.f_blocks) * 100, 1)
    total_gb = st.f_blocks * st.f_frsize / 1024**3
    used_gb = (st.f_blocks - st.f_bavail) * st.f_frsize / 1024**3
    return used_pct, f"{used_gb:.1f}G / {total_gb:.1f}G（{used_pct}%）"


def mem_stat() -> tuple[float, str]:
    info = {}
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            key, _, value = line.partition(":")
            info[key.strip()] = int(value.split()[0])  # KB
    total = info["MemTotal"]
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used_pct = round((total - avail) / total * 100, 1)
    return used_pct, f"{(total - avail) / 1024**2:.0f}M / {total / 1024**2:.1f}G（{used_pct}%）"


def uptime_str() -> str:
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        return f"{days} 天 {hours} 小时 {rem // 60} 分"
    except OSError:
        return "未知"


# ---------------------------------------------------------------- check 模式

def cmd_check(cfg: dict) -> None:
    disk_pct, disk_txt = disk_stat()
    mem_pct, mem_txt = mem_stat()
    svc = service_active()
    web = http_ok()

    problems: dict[str, str] = {}
    if not svc:
        problems["service"] = f"homepage.service 状态不是 active（{now_str()}）\n请运行: sudo systemctl status homepage"
    elif not web:
        problems["http"] = f"健康检查 {HEALTH_URL} 无响应（{now_str()}）\n服务进程在运行但网站不可用，请查看 logs/app.log"
    if disk_pct >= cfg["disk_th"]:
        problems["disk"] = f"根分区磁盘使用率 {disk_txt}，超过阈值 {cfg['disk_th']}%\n请清理大文件，避免日志/服务写盘失败"
    if mem_pct >= cfg["mem_th"]:
        problems["mem"] = f"内存使用率 {mem_txt}，超过阈值 {cfg['mem_th']}%\n可检查是否有异常进程占用"

    state = load_state()
    now = time.time()
    for key, title in CHECKS:
        st = state.setdefault(key, {"last_alert": 0})
        if key in problems:
            if now - st["last_alert"] >= cfg["cooldown"]:
                send_mail(cfg, f"紧急告警：{title}", problems[key] + "\n\n—— 服务器监控自动发送")
                st["last_alert"] = now
        elif st["last_alert"]:
            send_mail(cfg, f"已恢复：{title}", f"此前的问题已恢复正常（{now_str()}）。\n\n—— 服务器监控自动发送")
            st["last_alert"] = 0
    save_state(state)

    if not problems:
        print(f"[{now_str()}] 检查通过：服务正常，磁盘 {disk_pct}%，内存 {mem_pct}%")


# ---------------------------------------------------------------- report 模式

_ACCESS_RE = re.compile(r'\[access\] "(?P<method>[A-Z]+) (?P<path>[^"]*)" (?P<status>\d{3}) .*?ip=(?P<ip>[\d.]+)')
_USAGE_RE = re.compile(r"输入≈(\d+) 输出≈(\d+) tokens")


def _recent_log_files(name: str) -> list[Path]:
    """收集近 REPORT_DAYS 天的日志文件（含当天与轮转文件 app.log.2026-09-10）。"""
    files = []
    for path in LOG_DIR.glob(name + "*"):
        if path.name == name:
            files.append(path)
            continue
        try:
            file_date = date.fromisoformat(path.name.rsplit(".", 1)[-1])
        except ValueError:
            continue
        if (date.today() - file_date).days < REPORT_DAYS:
            files.append(path)
    return files


def collect_stats() -> dict:
    """从近 7 天日志统计访问与安全数据。"""
    stats = {
        "total": 0, "codes": Counter(), "ips": Counter(), "ai_asks": 0,
        "ai_tokens": 0, "suspect": 0, "denied": 0, "errors": 0,
    }
    for path in _recent_log_files("app.log"):
        for line in read_lines(path):
            if "[security]" in line:
                if "可疑路径探测" in line:
                    stats["suspect"] += 1
                elif "限流拦截" in line or "每日限额拦截" in line:
                    stats["denied"] += 1
                elif "服务端异常" in line:
                    stats["errors"] += 1
            if "AI 提问:" in line:
                stats["ai_asks"] += 1
            match = _USAGE_RE.search(line)
            if match:
                stats["ai_tokens"] += int(match.group(1)) + int(match.group(2))
                continue
            match = _ACCESS_RE.search(line)
            if match:
                stats["total"] += 1
                stats["codes"][match.group("status")] += 1
                stats["ips"][match.group("ip")] += 1
    return stats


def read_lines(path: Path):
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            yield from f
    except OSError:
        return


def cmd_report(cfg: dict) -> None:
    disk_pct, disk_txt = disk_stat()
    mem_pct, mem_txt = mem_stat()
    svc = "active" if service_active() else "非 active"
    try:
        la = os.getloadavg()
        load_txt = f"{la[0]:.2f} / {la[1]:.2f} / {la[2]:.2f}"
    except OSError:
        load_txt = "未知"

    s = collect_stats()
    codes = s["codes"]
    code_line = " / ".join(
        f"{k}xx: {sum(v for c, v in codes.items() if c.startswith(k))}"
        for k in "2345"
    )
    top_ips = "、".join(f"{ip}({n})" for ip, n in s["ips"].most_common(5)) or "无"

    start = date.today().toordinal() - REPORT_DAYS + 1
    body = f"""yjgnet.cn 运行周报（{date.fromordinal(start):%m-%d} ~ {date.today():%m-%d}）

【系统状态】
● 运行时长：{uptime_str()}
● 负载(1/5/15 分)：{load_txt}
● 磁盘：{disk_txt}
● 内存：{mem_txt}
● 应用服务：{svc}

【访问统计】
● 总请求数：{s['total']}
● 状态分布：{code_line}
● 独立 IP 数：{len(s['ips'])}
● 来源 TOP5：{top_ips}

【安全事件】
● 可疑路径探测：{s['suspect']} 次
● 限流/限额拦截：{s['denied']} 次
● 服务端异常：{s['errors']} 次

【AI 助手】
● 提问次数：{s['ai_asks']}
● 估算 token 用量：≈ {s['ai_tokens']:,}
● 当日预算：{load_env().get('CHAT_DAILY_TOKEN_BUDGET', '200000')}（超限自动降级预设知识库）

—— 由 server_monitor.py 自动发送，详细日志见 /opt/homepage/logs/
"""
    send_mail(cfg, "运行周报", body)


# ---------------------------------------------------------------- 状态文件

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- 入口

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    env = load_env()
    cfg = load_mail_config(env)
    if cfg is None:
        if mode == "test":
            print("邮件未启用或配置不完整（ALERT_EMAIL_ENABLED / ALERT_SMTP_USER / ALERT_SMTP_PASSWORD）。")
        return

    if mode == "check":
        cmd_check(cfg)
    elif mode == "report":
        cmd_report(cfg)
    elif mode == "test":
        send_mail(
            cfg, "测试邮件：监控配置正常",
            f"这是一封测试邮件，说明 SMTP 配置与 cron 监控已就绪（{now_str()}）。\n\n"
            "之后出现紧急异常会立即告警，每周一自动发送运行报告。\n\n—— 服务器监控自动发送",
        )
    else:
        print(f"未知模式：{mode}（可选 check / report / test）")
        sys.exit(1)


if __name__ == "__main__":
    main()
