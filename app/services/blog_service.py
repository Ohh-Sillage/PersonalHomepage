"""博客文章服务。

扫描 content/posts/*.md（front matter + Markdown 渲染），
按目录 mtime 指纹缓存，新增/修改文章后自动生效。
"""

from pathlib import Path

import frontmatter
import markdown

from app.config import BASE_DIR

POSTS_DIR = BASE_DIR / "content" / "posts"

_MD_EXTENSIONS = ["fenced_code", "codehilite", "tables", "toc", "attr_list"]
_MD_CONFIGS = {
    "codehilite": {"css_class": "highlight", "guess_lang": False, "linenums": False}
}

_posts_cache: dict[str, dict] = {}
_fingerprint: tuple = ()


def _render_markdown(text: str) -> str:
    # Markdown 实例有状态，每次渲染新建，避免并发复用问题
    md = markdown.Markdown(extensions=_MD_EXTENSIONS, extension_configs=_MD_CONFIGS)
    return md.convert(text)


def _parse_file(path: Path) -> dict:
    post = frontmatter.load(path)
    meta = post.metadata
    raw_date = meta.get("date", "")
    date_str = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date)
    return {
        "slug": path.stem,
        "title": str(meta.get("title", path.stem)),
        "date": date_str,
        "tags": [str(t) for t in (meta.get("tags") or [])],
        "summary": str(meta.get("summary", "")),
        "content": _render_markdown(post.content),
        "reading_minutes": max(1, len(post.content) // 600),
    }


def _dir_fingerprint() -> tuple:
    return tuple(sorted((p.name, p.stat().st_mtime) for p in POSTS_DIR.glob("*.md")))


def _ensure_cache() -> None:
    global _posts_cache, _fingerprint

    fp = _dir_fingerprint()
    if fp != _fingerprint:
        _posts_cache = {
            path.stem: _parse_file(path) for path in sorted(POSTS_DIR.glob("*.md"))
        }
        _fingerprint = fp


def get_posts() -> list[dict]:
    """全部文章，按日期倒序。"""
    _ensure_cache()
    posts = list(_posts_cache.values())
    posts.sort(key=lambda p: p["date"] or "", reverse=True)
    return posts


def get_post(slug: str) -> dict | None:
    """按 slug 获取单篇文章，不存在返回 None。"""
    _ensure_cache()
    return _posts_cache.get(slug)
