# syntax=docker/dockerfile:1
# ─── 玄同 Xuantong 生产镜像（多阶段构建，无 GPU 依赖）──────────────────────

# Stage 1: Builder —— 安装全部运行时依赖到 site-packages
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 复制打包元数据与包目录；setuptools 构建 wheel 时必须能发现 app 包。
COPY pyproject.toml README.md ./
COPY app/ ./app/
RUN pip install --upgrade pip && \
    pip install ".[postgres]"

# Stage 2: Runtime —— 精简运行镜像
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/xuantong/.local/bin:${PATH}"

WORKDIR /app

# 创建非 root 运行用户
RUN groupadd -r xuantong && useradd -r -g xuantong -m -d /home/xuantong xuantong

# 从 builder 复制已安装的依赖与可执行入口（uvicorn / alembic 等）
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制应用源码与数据库迁移脚本（含 app/xuantong/rag/data 语料）
COPY --chown=xuantong:xuantong app/ ./app/
COPY --chown=xuantong:xuantong alembic/ ./alembic/
COPY --chown=xuantong:xuantong alembic.ini ./

USER xuantong

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
