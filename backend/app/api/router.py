from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import (
    accounts,
    auth,
    categories,
    imports,
    meta,
    reports,
    rules,
    transactions,
)

api_router = APIRouter()
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(categories.router)
api_router.include_router(transactions.router)
api_router.include_router(imports.router)
api_router.include_router(rules.router)
api_router.include_router(reports.router)

# 后续里程碑挂载点：
#   M2  imports 增加截图上传（OCR）与 CSV 来源
#   M4  budgets / recurring
