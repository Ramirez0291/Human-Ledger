# 单容器部署：前端构建产物由 FastAPI 一并托管，无需额外的 Web 服务器。

# ---- 阶段 1：构建前端 ----
FROM node:22-alpine AS frontend

WORKDIR /build
# 先只拷依赖清单，让 npm 层能被缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ---- 阶段 2：后端运行时 ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tokyo

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# SQLite 文件与上传的截图都在此目录，必须挂载为卷，否则容器重建即丢数据
VOLUME ["/app/data"]
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
