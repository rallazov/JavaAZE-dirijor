# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Dirijor Supervisor – LangGraph Consensus Brain

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# Story 3.1: /health returns 200 when every required dep is ready, 503 otherwise.
# Using stdlib urllib keeps the python:3.12-slim base lean (no curl install).
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)" \
    || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
