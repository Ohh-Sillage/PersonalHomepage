"""主页路由。"""

from fastapi import APIRouter, Request

from app.services.blog_service import get_posts
from app.templating import base_context, templates

router = APIRouter()


@router.get("/")
async def index(request: Request):
    ctx = base_context()
    ctx["posts"] = get_posts()[:3]
    return templates.TemplateResponse(request, "index.html", ctx)
