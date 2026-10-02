FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY data ./data
COPY 政策证据包 ./政策证据包
RUN mkdir -p /app/storage/uploads && \
    useradd --create-home --uid 10001 huimin && \
    chown -R huimin:huimin /app/storage
USER huimin
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

