"""HTTP 中间件：访问日志与安全事件记录（配合 app/logger.py 使用）。"""

import time

from starlette.requests import Request

from app.logger import get_logger, security_logger

_access_log = get_logger("access")

# 本站不存在这些路径或特征，命中即视为扫描探测（仅记录，不影响正常请求）
_SCAN_HINTS = (
    ".php", "wp-", "wordpress", "phpmyadmin", "phpinfo", "xmlrpc",
    ".env", ".git", "cgi-bin", "/admin", "passwd", "../", "eval(",
    "actuator", "jenkins", "shell",
)


def get_client_ip(request: Request) -> str:
    """访客真实 IP：优先 nginx 注入的 X-Real-IP，其次 X-Forwarded-For 首项。

    nginx 反代后 request.client.host 恒为 127.0.0.1，必须取代理头；
    应用仅监听 127.0.0.1，外部无法绕过 nginx 伪造这些头。
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _full_path(request: Request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def _is_suspicious(path: str) -> bool:
    low = path.lower()
    return any(hint in low for hint in _SCAN_HINTS)


async def access_log_middleware(request: Request, call_next):
    """记录每个请求（方法/路径/状态码/耗时/IP/UA），并单独归类安全事件。"""
    start = time.perf_counter()
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "-")

    try:
        response = await call_next(request)
    except Exception:
        cost_ms = (time.perf_counter() - start) * 1000
        _access_log.exception(
            '"%s %s" 500 %.1fms ip=%s ua="%s"',
            request.method, _full_path(request), cost_ms, ip, ua,
        )
        security_logger().error(
            "服务端异常: ip=%s %s %s", ip, request.method, _full_path(request)
        )
        raise

    cost_ms = (time.perf_counter() - start) * 1000
    _access_log.info(
        '"%s %s" %d %.1fms ip=%s ua="%s"',
        request.method, _full_path(request), response.status_code, cost_ms, ip, ua,
    )

    if _is_suspicious(request.url.path):
        security_logger().warning(
            '可疑路径探测: ip=%s %s %s ua="%s"',
            ip, request.method, _full_path(request), ua,
        )
    elif response.status_code >= 400:
        security_logger().warning(
            "%d 响应: ip=%s %s %s",
            response.status_code, ip, request.method, _full_path(request),
        )

    return response
