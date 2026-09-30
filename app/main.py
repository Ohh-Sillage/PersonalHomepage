"""个人主页 FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import BASE_DIR, settings
from app.logger import get_logger, setup_logging
from app.middleware import access_log_middleware
from app.routers import blog, chat, pages
from app.templating import base_context, templates

setup_logging()
log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动/关闭日志：为排查重启、掉线问题留时间锚点。"""
    log.info(
        "应用启动: %s（LLM: %s）",
        settings.site_url,
        "已配置" if settings.llm_api_key else "未配置，使用预设知识库",
    )
    yield
    log.info("应用关闭")


app = FastAPI(title="Personal Homepage", docs_url=None, redoc_url=None, lifespan=lifespan)

app.middleware("http")(access_log_middleware)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(pages.router)
app.include_router(blog.router)
app.include_router(chat.router)


@app.get("/api/health")
async def health():
    """健康检查（部署验证与监控用）。"""
    return {"status": "ok"}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """浏览器访问 404 时返回友好的 HTML 页面，接口请求仍返回 JSON。"""
    accept = request.headers.get("accept", "")
    if exc.status_code == 404 and "text/html" in accept:
        ctx = base_context()
        ctx["message"] = exc.detail if isinstance(exc.detail, str) else "页面不存在"
        return templates.TemplateResponse(request, "404.html", ctx, status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
