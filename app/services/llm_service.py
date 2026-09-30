"""AI 助手回复服务。

默认使用基于 site.yml 的预设知识库回答（带打字机流式效果）；
在 .env 中配置 LLM_API_KEY 后，自动切换为 OpenAI 兼容接口的真实模型流式调用。
"""

import asyncio
import json
import random
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.site_content import load_site

# 关键词 -> 回答生成函数
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("技能", "技术栈", "会什么", "擅长", "技术能力", "skill"), "skills"),
    (("项目", "作品", "做过", "project", "开源"), "projects"),
    (("经历", "工作", "公司", "经验", "experience", "履历"), "experience"),
    (("简历", "resume", "cv"), "resume"),
    (("博客", "文章", "写作", "blog"), "blog"),
    (("联系", "邮箱", "email", "怎么找", "合作", "招"), "contact"),
    (("你好", "您好", "hi", "hello", "嗨", "在吗"), "greeting"),
    (("是谁", "介绍", "自我介绍", "你是", "什么方向", "背景"), "about"),
]


def _answer_skills(site: dict) -> str:
    lines = ["他/她的主要技术栈如下："]
    for group in site.get("skills") or []:
        lines.append(f"- {group.get('category')}：{'、'.join(group.get('items') or [])}")
    return "\n".join(lines)


def _answer_projects(site: dict) -> str:
    projects = site.get("projects") or []
    if not projects:
        return "暂时还没有收录项目信息。"
    lines = ["他/她做过的一些代表项目："]
    for p in projects:
        tags = "、".join(p.get("tags") or [])
        lines.append(f"- {p.get('name')}：{p.get('description')}（{tags}）")
    lines.append("更多细节可以在主页的「项目作品」板块查看。")
    return "\n".join(lines)


def _answer_experience(site: dict) -> str:
    jobs = site.get("experience") or []
    if not jobs:
        return "暂时还没有收录经历信息。"
    lines = ["他/她的工作经历概况："]
    for j in jobs:
        lines.append(f"- {j.get('period')}：{j.get('role')} @ {j.get('company')}")
    return "\n".join(lines)


def _answer_resume(site: dict) -> str:
    url = site.get("resume_url", "")
    if url:
        return f"简历可以在这里下载：{url}\n也可以直接在主页底部点击「下载简历 PDF」按钮。"
    return "简历暂时还没有上传，可以直接发邮件和他/她联系。"


def _answer_blog(site: dict) -> str:
    return "他/她会不定期分享 AI 相关的技术文章，可以在主页的「近期文章」板块或博客页查看。"


def _answer_contact(site: dict) -> str:
    email = site.get("email", "")
    lines = ["可以通过以下方式联系他/她："]
    if email:
        lines.append(f"- 邮箱：{email}")
    for s in site.get("socials") or []:
        lines.append(f"- {s.get('name')}：{s.get('url')}")
    return "\n".join(lines)


def _answer_greeting(site: dict) -> str:
    name = site.get("name", "本站主人")
    return (
        f"你好！我是 {name} 个人主页上的 AI 助手。"
        f"你可以问我关于他/她的技能、项目、工作经历、文章或者联系方式等问题。"
    )


def _answer_about(site: dict) -> str:
    name = site.get("name", "本站主人")
    title = site.get("title", "")
    intro = site.get("intro") or []
    first = intro[0] if intro else ""
    return f"{name} 目前是一名{title}。{first}"


_ANSWER_BUILDERS = {
    "skills": _answer_skills,
    "projects": _answer_projects,
    "experience": _answer_experience,
    "resume": _answer_resume,
    "blog": _answer_blog,
    "contact": _answer_contact,
    "greeting": _answer_greeting,
    "about": _answer_about,
}


def _preset_answer(message: str) -> str:
    site = load_site()
    text = message.lower()
    for keywords, kind in _KEYWORD_RULES:
        if any(k in text for k in keywords):
            return _ANSWER_BUILDERS[kind](site)
    name = site.get("name", "本站主人")
    return (
        f"这个问题我暂时还回答不了。目前我比较擅长介绍 {name} 的技能、项目、"
        f"工作经历、文章和联系方式，你可以换个角度问问看。"
    )


def _build_system_prompt(site: dict) -> str:
    """把 site.yml 精简为 LLM 系统提示词（控制 token 用量）。"""
    profile = {
        "姓名": site.get("name"),
        "职位": site.get("title"),
        "简介": site.get("intro"),
        "邮箱": site.get("email"),
        "技能": site.get("skills"),
        "工作经历": site.get("experience"),
        "项目": site.get("projects"),
    }
    return (
        "你是个人主页网站上的 AI 助手，负责向访客介绍网站主人的背景、技能、"
        "项目和经历。请用简洁友好、口语化的中文回答，不要编造资料中没有的信息。\n\n"
        f"主人资料（JSON）：\n{json.dumps(profile, ensure_ascii=False)}"
    )


def _estimate_tokens(text: str) -> int:
    """按字符数粗估 token 用量（中英混合约 2 字符 ≈ 1 token），仅用于预算防护。"""
    return max(1, len(text) // 2)


async def _stream_llm(message: str, history: list[dict], stats: dict) -> AsyncIterator[str]:
    """调用 OpenAI 兼容接口，流式产出文本增量，并把估算用量写入 stats。"""
    site = load_site()
    messages = [{"role": "system", "content": _build_system_prompt(site)}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": True,
        "max_tokens": settings.llm_max_tokens,  # 单次生成上限，防止被诱导输出超长内容
    }
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"

    stats["input_tokens"] = _estimate_tokens("".join(m["content"] for m in messages))
    output_chars = 0

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        output_chars += len(delta)
                        yield delta
    finally:
        # 流中断（客户端断开/异常）时也把已产生的用量计入预算
        stats["output_tokens"] = max(1, output_chars // 2) if output_chars else 0


async def stream_reply(
    message: str,
    history: list[dict],
    stats: dict | None = None,
    allow_llm: bool = True,
) -> AsyncIterator[str]:
    """统一回复入口：产出文本增量（delta）。

    allow_llm 且配置了 LLM Key 时走真实模型（用量写入 stats）；
    否则用预设知识库答案模拟打字机流式输出（不消耗 token）。
    """
    if stats is None:
        stats = {}

    if allow_llm and settings.llm_api_key:
        async for delta in _stream_llm(message, history, stats):
            yield delta
        return

    answer = _preset_answer(message)
    pos = 0
    while pos < len(answer):
        step = random.randint(2, 6)
        yield answer[pos : pos + step]
        pos += step
        await asyncio.sleep(0.015)
