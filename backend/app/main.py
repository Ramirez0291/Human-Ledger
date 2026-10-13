"""应用入口。

生产形态为单进程：FastAPI 同时提供 /api 与前端静态文件。
开发时前端跑 Vite dev server，由其代理 /api 到本服务。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import PROJECT_ROOT, settings

logging.basicConfig(level=logging.INFO if not settings.debug else logging.DEBUG)
logger = logging.getLogger("renlei")

# 前端构建产物；未构建时（纯后端开发）跳过挂载
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger.info("启动 %s | env=%s | db=%s", settings.app_name, settings.app_env, settings.resolved_database_url)
    logger.info("数据目录：%s", settings.data_dir)
    if settings.ocr_provider == "none":
        logger.info("截图识别：未配置（M0 阶段仅预留接口）")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.3.0-M3",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# 仅开发环境放开跨域：Vite dev server 与后端不同端口
if not settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix="/api")


if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 路由回退：非 /api 路径一律交给前端路由处理。"""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not_found"}, status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def dev_hint():
        return JSONResponse(
            {
                "app": settings.app_name,
                "hint": "前端尚未构建。开发模式请另起 Vite：cd frontend && npm run dev（http://localhost:5173）",
                "api_docs": "/api/docs",
            }
        )
