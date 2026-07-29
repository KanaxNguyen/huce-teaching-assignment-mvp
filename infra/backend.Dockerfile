FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir /app/apps/api
COPY data/fixtures /app/data/fixtures
RUN mkdir -p /app/storage/database /app/storage/uploads /app/storage/exports
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8000"]

