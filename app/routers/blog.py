"""博客路由：列表页与详情页。"""

from fastapi import APIRouter, HTTPException, Request

from app.services.blog_service import get_post, get_posts
from app.templating import base_context, templates

router = APIRouter()


@router.get("/blog")
async def blog_list(request: Request):
    ctx = base_context()
    ctx["posts"] = get_posts()
    return templates.TemplateResponse(request, "blog_list.html", ctx)


@router.get("/blog/{slug}")
async def blog_detail(request: Request, slug: str):
    post = get_post(slug)
    if post is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    ctx = base_context()
    ctx["post"] = post
    return templates.TemplateResponse(request, "blog_detail.html", ctx)
