"""聊天接口：POST /api/chat，SSE 流式返回。"""

import json
import time
from collections import defaultdict, deque
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import BASE_DIR, settings
from app.logger import get_logger, security_logger
from app.middleware import get_client_ip
from app.services.llm_service import stream_reply

router = APIRouter()
_chat_log = get_logger("chat")

# 分钟级限流：IP -> 请求时间戳队列
_hits: dict[str, deque] = defaultdict(deque)

# 每日用量（防 token 恶意消耗）：进程内缓存 + logs/llm_usage.json 持久化
_USAGE_FILE = BASE_DIR / "logs" / "llm_usage.json"
_usage: dict = {"date": "", "total_tokens": 0, "ips": {}}


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= settings.chat_rate_limit:
        return False
    q.append(now)
    return True


def _load_usage() -> None:
    """加载当日用量；跨天自动清零，服务重启后从文件恢复。"""
    today = date.today().isoformat()
    if _usage["date"] == today:
        return
    _usage.update({"date": today, "total_tokens": 0, "ips": {}})
    try:
        data = json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
        if data.get("date") == today:
            _usage["total_tokens"] = int(data.get("total_tokens") or 0)
            _usage["ips"] = data.get("ips") or {}
    except (OSError, ValueError, TypeError):
        pass


def _save_usage() -> None:
    """原子落盘（先写临时文件再替换），失败不影响聊天功能。"""
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_usage, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_USAGE_FILE)
    except OSError:
        pass


def _ip_usage(ip: str) -> dict:
    _load_usage()
    return _usage["ips"].setdefault(ip, {"count": 0, "tokens": 0})


def _record_usage(ip: str, stats: dict) -> None:
    """累计本次请求的估算 token 用量并持久化。"""
    input_tokens = int(stats.get("input_tokens") or 0)
    output_tokens = int(stats.get("output_tokens") or 0)
    total = input_tokens + output_tokens
    if total <= 0:
        return
    entry = _ip_usage(ip)
    entry["tokens"] += total
    _usage["total_tokens"] += total
    _save_usage()
    _chat_log.info(
        "AI 用量: ip=%s 输入≈%d 输出≈%d tokens；当日全站≈%d/%d，该 IP %d 次/≈%d tokens",
        ip, input_tokens, output_tokens,
        _usage["total_tokens"], settings.chat_daily_token_budget,
        entry["count"], entry["tokens"],
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    ip = get_client_ip(request)
    if not _check_rate_limit(ip):
        security_logger().warning(
            "限流拦截: ip=%s 超过 %d 次/分钟", ip, settings.chat_rate_limit
        )
        return JSONResponse(
            {"error": "提问太频繁啦，请稍等一分钟再试。"}, status_code=429
        )

    # 每 IP 每日次数限制（防单 IP 刷量）
    entry = _ip_usage(ip)
    if entry["count"] >= settings.chat_daily_limit_per_ip:
        security_logger().warning(
            "每日限额拦截: ip=%s 当日已提问 %d 次（上限 %d）",
            ip, entry["count"], settings.chat_daily_limit_per_ip,
        )
        return JSONResponse(
            {"error": "今天的提问次数已用完，明天再来吧。"}, status_code=429
        )
    entry["count"] += 1
    _save_usage()

    # 全站 token 预算：耗尽后降级为预设知识库（不再产生 API 费用）
    allow_llm = _usage["total_tokens"] < settings.chat_daily_token_budget
    if settings.llm_api_key and not allow_llm:
        _chat_log.warning(
            "AI 预算耗尽，降级预设知识库: 当日全站≈%d/%d tokens",
            _usage["total_tokens"], settings.chat_daily_token_budget,
        )

    _chat_log.info("AI 提问: ip=%s 长度=%d 历史=%d 条", ip, len(req.message), len(req.history))

    # 只保留最近几轮、且只允许标准角色（防止前端注入异常内容）
    history = [
        {"role": m.role, "content": m.content}
        for m in req.history
        if m.role in ("user", "assistant")
    ][-8:]

    stats: dict = {}

    async def event_stream():
        try:
            async for delta in stream_reply(req.message, history, stats=stats, allow_llm=allow_llm):
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        except Exception:
            _chat_log.exception("AI 回复失败: ip=%s", ip)
            msg = {"error": "AI 服务暂时不可用，请稍后再试。"}
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        _record_usage(ip, stats)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 下禁用缓冲，保证流式实时性
        },
    )
