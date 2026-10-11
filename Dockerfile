FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 先装依赖再拷代码：改代码不会让依赖层缓存失效
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY samples ./samples

# 数据和上传目录挂卷，容器重建不丢
RUN mkdir -p /data/uploads
ENV UPLOAD_DIR=/data/uploads \
    DATABASE_URL=sqlite:////data/app.db \
    QDRANT_URL=http://qdrant:6333

EXPOSE 8000
# 健康检查用 /healthz：它同时暴露 tokenizer / embedding_provider / llm_configured，
# 出问题时一眼能看出是"服务挂了"还是"配置退化了"
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
