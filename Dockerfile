FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 api \
    && useradd --uid 10001 --gid api --create-home api \
    && mkdir -p /app/data/moodboards \
    && chown -R api:api /app/data
COPY --chown=api:api app ./app
COPY --chown=api:api tests ./tests
USER api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
