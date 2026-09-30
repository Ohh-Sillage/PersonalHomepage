"""共享的 Jinja2 模板实例与公共上下文。"""

from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR
from app.site_content import load_site

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def base_context() -> dict:
    """所有页面公共上下文（base.html 需要 site 数据）。"""
    return {"site": load_site(), "now_year": datetime.now().year}
