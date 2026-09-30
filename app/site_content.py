"""加载 content/site.yml 站点内容。

带 mtime 缓存：修改 site.yml 后无需重启服务，下次请求自动重载。
"""

import yaml

from app.config import BASE_DIR

SITE_FILE = BASE_DIR / "content" / "site.yml"

_cache: dict | None = None
_cache_mtime: float = 0.0


def load_site() -> dict:
    """返回站点内容配置（dict）。"""
    global _cache, _cache_mtime

    mtime = SITE_FILE.stat().st_mtime
    if _cache is None or mtime != _cache_mtime:
        with SITE_FILE.open(encoding="utf-8") as f:
            _cache = yaml.safe_load(f)
        _cache_mtime = mtime

    return _cache
