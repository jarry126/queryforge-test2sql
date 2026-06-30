# QueryForge 应用镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_WORKERS=1

WORKDIR /app

# 先装依赖（利用层缓存）
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[eval]"

COPY eval ./eval
COPY scripts ./scripts
COPY static ./static
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# 默认单 worker：避免进程内状态、Prometheus 指标与连接池在多 worker 下被放大。
# 需要横向扩容时优先增加容器副本；确需单容器多 worker 时显式设置 APP_WORKERS。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${APP_WORKERS}"]
