FROM python:3.12-slim

WORKDIR /app

# Installed before the source is copied so the dependency layer stays cached
# across code changes. Only the deps land here - packages.find matches nothing
# yet, so the built wheel is empty and the source below is what gets imported
# (uvicorn resolves app.main from WORKDIR).
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
