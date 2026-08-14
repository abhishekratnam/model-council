FROM python:3.12-slim

WORKDIR /app

COPY --chown=65532:65532 server.py ./
COPY --chown=65532:65532 static ./static

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

USER 65532:65532
EXPOSE 8080

# Cloud Run supplies PORT. --allow-network is intentional inside this
# container; external browser origins remain restricted by the allowlist.
CMD ["/bin/sh", "-c", "exec python3 server.py --host 0.0.0.0 --port \"${PORT}\" --allow-network"]
