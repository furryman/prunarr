# --- Build stage: install dependencies into a virtual env ---
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# --- Runtime stage: lean final image ---
FROM python:3.12-slim

ARG PUID=1000
ARG PGID=1000
RUN groupadd -g ${PGID} prunarr && useradd -u ${PUID} -g prunarr -d /app prunarr && \
    mkdir -p /config && chown prunarr:prunarr /config

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY app/ ./app/

USER prunarr
EXPOSE 8585
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8585"]
