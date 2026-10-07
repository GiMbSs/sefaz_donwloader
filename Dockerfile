FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG INSTALL_DEV=false

RUN addgroup --system app && adduser --system --ingroup app app

COPY . /app

RUN if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir ".[dev]"; else pip install --no-cache-dir .; fi && \
    mkdir -p /app/staticfiles && \
    chown -R app:app /app

USER app

EXPOSE 8000
