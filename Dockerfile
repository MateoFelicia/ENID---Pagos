FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=app.py \
    TRUST_PROXY=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 enid \
    && chmod +x docker/entrypoint.sh \
    && chown -R enid:enid /app
USER enid

EXPOSE 8000

# Los hostings que exponen la app por otro puerto definen PORT
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/salud' % os.environ.get('PORT', '8000'), timeout=4)"

ENTRYPOINT ["docker/entrypoint.sh"]
# Un solo proceso con varios hilos: alcanza de sobra para una escuela y mantiene consistente el límite de
# intentos de inicio de sesión. Si subís WEB_CONCURRENCY, definí RATELIMIT_STORAGE_URI (Redis) para compartirlo.
CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --worker-class gthread --workers ${WEB_CONCURRENCY:-1} --threads ${WEB_THREADS:-8} --timeout 60 --access-logfile -"]
