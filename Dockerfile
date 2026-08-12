# One image with the whole of Cascade, for platforms that deploy a single
# service from a repository (Railway, Fly, Render).
#
# It exists alongside backend/Dockerfile and frontend/Dockerfile rather than
# replacing them: docker compose keeps running two containers with nginx in
# front, which is the right shape locally. Here nginx would only add a second
# process to route between two things that can share one port, and on a
# platform where each service is its own deployment it would also need to
# discover the backend over the private network.

FROM node:22-alpine AS web
WORKDIR /web
# Manifests first so the dependency layer survives frontend source changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
WORKDIR /app

# ffmpeg merges the video and audio tracks of qualities that arrive separated.
# Without it the only downloadable quality on YouTube would be 360p - the one
# format of its 33 that carries both together. It only ever remuxes (-c copy),
# never re-encodes, so it costs image size but not CPU.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Installed before the source is copied so the dependency layer stays cached
# across code changes. Only the deps land here - packages.find matches nothing
# yet, so the built wheel is empty and the source below is what gets imported.
COPY backend/pyproject.toml .
RUN pip install --no-cache-dir .

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .

# Where app.main looks for the SPA. Present here, absent in a plain checkout.
COPY --from=web /web/dist ./static

# Staging for files in transit. Mount a persistent volume here, or a redeploy
# throws away whatever was mid-download - the engine resumes, but only if the
# partial file survived.
ENV DOWNLOAD_ROOT=/downloads

# $PORT because the platform picks it; the fallback keeps `docker run` working.
# Migrations run first: the image is the only thing that knows which revision
# the code expects.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
