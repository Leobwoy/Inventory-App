# Koyeb (or any container host). Slim rather than alpine: psycopg2-binary ships
# manylinux wheels that alpine's musl cannot use, forcing a source build.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=app:create_app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Koyeb injects PORT; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Migrations run at start, not at build: the build stage has no DATABASE_URL.
# Single web dyno, so this is safe; it needs revisiting if ever scaled out.
CMD ["sh", "-c", "flask db upgrade && exec gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 2 --timeout 60 --access-logfile -"]
