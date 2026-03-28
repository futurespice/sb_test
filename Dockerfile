FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        build-essential \
        fontconfig \
        libfontconfig1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . /app/

RUN mkdir -p /app/media /app/static

# collectstatic не требует DB — запускаем на этапе сборки образа.
# SECRET_KEY здесь дамми — реальный ключ будет подставлен через .env в runtime.
RUN SECRET_KEY=build-time-dummy \
    DEBUG=False \
    DB_HOST=localhost \
    python manage.py collectstatic --noinput --clear

# Безопасность: запускаем процесс от непривилегированного пользователя.
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["gunicorn", "core_project.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
