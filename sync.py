"""一键同步工具：把本地改动同步到服务器（yjgnet.cn）。

用法（在项目根目录执行，需已安装 paramiko：pip install paramiko）：

    python sync.py content     # 只同步文章/文案（秒级，无需重启服务）
    python sync.py static      # 只同步图片/简历等静态资源（无需重启）
    python sync.py app         # 只同步后端代码（自动重启服务）
    python sync.py templates   # 只同步页面模板（自动重启服务）
    python sync.py env         # 只同步 .env 配置到服务器（自动重启服务）
    python sync.py all         # 全量同步全部文件（自动重启服务）
    python sync.py logs        # 拉取服务器日志到本地 logs/server/（排查问题用）

配置：deploy/.sync_config.json（host / user / password / remote_root）。
优先使用 SSH 密钥免密登录（~/.ssh/id_ed25519 或 id_rsa），不可用时回退密码。
"""

import posixpath
import sys
import time
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOCAL_ROOT = Path(__file__).resolve().parent
CONFIG_FILE = LOCAL_ROOT / "deploy" / ".sync_config.json"

# 各同步目标：目录或文件相对路径 -> 是否需要重启服务
TARGETS = {
    "content": (["content"], False),          # site.yml 与文章有自动重载，无需重启
    "static": (["static"], False),
    "app": (["app"], True),
    "templates": (["templates"], True),
    "deploy": (["deploy"], True),
    "env": ([".env"], True),            # .env 含密钥与授权码，仅在显式调用时上传
    "all": (
        ["app", "content", "templates", "static", "deploy",
         "requirements.txt", "README.md", ".env.example",
         "ARCHITECTURE.md", "DESIGN_DECISIONS.md", "USAGE_GUIDE.md"],
        True,
    ),
}

EXCLUDE = {"__pycache__", ".git", ".venv", "venv", ".env", ".sync_config.json"}


def load_config() -> dict:
    import json

    if not CONFIG_FILE.exists():
        print(f"缺少配置文件：{CONFIG_FILE}")
        print('请创建，内容示例：{"host":"146.56.223.180","user":"ubuntu","password":"你的密码","remote_root":"/opt/homepage"}')
        sys.exit(1)
    with CONFIG_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def connect(cfg: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # 优先尝试本地 SSH 密钥（有则免密），否则回退密码
    key_files = [
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_rsa",
    ]
    existing = [str(k) for k in key_files if k.exists()]

    try:
        if existing:
            client.connect(cfg["host"], username=cfg["user"], key_filename=existing, timeout=15)
        else:
            raise paramiko.AuthenticationException()
    except (paramiko.SSHException, paramiko.AuthenticationException):
        client.connect(cfg["host"], username=cfg["user"], password=cfg["password"], timeout=15)
    return client


def run_sudo(client, cmd: str, password: str, timeout: int = 120):
    import shlex

    stdin, stdout, stderr = client.exec_command(
        f"sudo -S -p '' bash -lc {shlex.quote(cmd)}", timeout=timeout
    )
    stdin.write(password + "\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def upload_tree(sftp, local: Path, remote: str) -> int:
    count = 0
    for item in sorted(local.iterdir()):
        if item.name in EXCLUDE:
            continue
        rpath = posixpath.join(remote, item.name)
        if item.is_dir():
            try:
                sftp.stat(rpath)
            except IOError:
                sftp.mkdir(rpath)
            count += upload_tree(sftp, item, rpath)
        else:
            sftp.put(str(item), rpath)
            count += 1
            print("  上传:", rpath)
    return count


def pull_logs(client, cfg: dict) -> None:
    """把服务器上的 logs/ 目录下载到本地 logs/server/（不改动服务器内容）。"""
    import stat

    password = cfg.get("password", "")
    remote_logs = posixpath.join(cfg["remote_root"], "logs")

    code, out, _ = run_sudo(client, f"test -d {remote_logs} && echo YES || echo NO", password)
    if "YES" not in out:
        print("服务器上还没有日志目录（应用尚未运行或未产生日志）。")
        return

    # 临时把日志目录属主交给登录用户以下载，完成后归还服务用户
    run_sudo(client, f"chown -R {cfg['user']} {remote_logs}", password)
    local_dir = LOCAL_ROOT / "logs" / "server"
    local_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    sftp = client.open_sftp()
    try:
        stack = [(remote_logs, local_dir)]
        while stack:
            remote_dir, local_path = stack.pop()
            local_path.mkdir(parents=True, exist_ok=True)
            for entry in sftp.listdir_attr(remote_dir):
                rpath = posixpath.join(remote_dir, entry.filename)
                lpath = local_path / entry.filename
                if stat.S_ISDIR(entry.st_mode):
                    stack.append((rpath, lpath))
                else:
                    sftp.get(rpath, str(lpath))
                    count += 1
                    print("  下载:", rpath)
    finally:
        sftp.close()
        run_sudo(client, f"chown -R homepage:homepage {remote_logs}", password)

    print(f"日志已下载到 {local_dir}（共 {count} 个文件）。")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "logs":
        cfg = load_config()
        print(f"连接 {cfg['host']} ...")
        client = connect(cfg)
        try:
            pull_logs(client, cfg)
        finally:
            client.close()
        return

    if mode not in TARGETS:
        print(f"未知模式：{mode}，可选：{', '.join(list(TARGETS) + ['logs'])}")
        sys.exit(1)

    paths, need_restart = TARGETS[mode]
    cfg = load_config()
    remote_root = cfg["remote_root"]

    print(f"连接 {cfg['host']} ...")
    client = connect(cfg)
    try:
        # 临时把远端目录写权限交给登录用户，上传后再归还服务用户
        code, out, err = run_sudo(client, f"chown -R {cfg['user']} {remote_root}", cfg.get("password", ""))
        if code != 0:
            print("chown 失败：", err.strip())
            sys.exit(1)

        sftp = client.open_sftp()
        total = 0
        try:
            for rel in paths:
                local = LOCAL_ROOT / rel
                if not local.exists():
                    print("  跳过不存在:", rel)
                    continue
                if local.is_dir():
                    total += upload_tree(sftp, local, posixpath.join(remote_root, rel))
                else:
                    sftp.put(str(local), posixpath.join(remote_root, rel))
                    total += 1
                    print("  上传:", rel)
        finally:
            sftp.close()

        code, out, err = run_sudo(
            client,
            f"chown -R homepage:homepage {remote_root}"
            f" && rm -rf {remote_root}/app/__pycache__ {remote_root}/app/*/__pycache__"
            f" && (test ! -f {remote_root}/.env || chmod 640 {remote_root}/.env)",
            cfg.get("password", ""),
        )
        if code != 0:
            print("属主恢复失败：", err.strip())

        if need_restart and cfg.get("password"):
            print("重启服务 ...")
            run_sudo(client, "systemctl restart homepage", cfg["password"])
            # 服务刚重启时端口可能尚未就绪，重试几次再判定
            health = ""
            for _ in range(6):
                time.sleep(1)
                _, out, _ = client.exec_command("curl -s -m 3 http://127.0.0.1:8000/api/health")
                health = out.read().decode().strip()
                if health:
                    break
            print("健康检查:", health or "无响应（请检查 sudo systemctl status homepage）")

        print(f"同步完成：{total} 个文件。")
        print("访问 https://yjgnet.cn 查看效果。")
    finally:
        client.close()


if __name__ == "__main__":
    main()
