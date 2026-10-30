# Render free web service (Docker). Build context is the repository root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000 \
    UPLOAD_DIR=/tmp/huce/uploads EXPORT_DIR=/tmp/huce/exports SOURCE_DIR=/tmp/huce/source
RUN useradd -m -u 1000 user && mkdir -p /tmp/huce && chown -R user /tmp/huce
WORKDIR /app
COPY apps/api/requirements.deploy.txt apps/api/requirements.deploy.txt
RUN pip install --no-cache-dir --requirement apps/api/requirements.deploy.txt
COPY apps/api apps/api
COPY alembic.ini alembic.ini
COPY deploy/huggingface/entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh && chown -R user /app
USER user
EXPOSE 10000
CMD ["./entrypoint.sh"]
