FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api/requirements.deploy.txt /app/apps/api/requirements.deploy.txt
RUN pip install --no-cache-dir --requirement /app/apps/api/requirements.deploy.txt
COPY apps/api /app/apps/api
COPY alembic.ini /app/alembic.ini
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8000"]
