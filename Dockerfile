FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY docker ./docker

RUN chmod +x docker/backend-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/backend-entrypoint.sh"]
