# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Dirijor Supervisor – LangGraph Consensus Brain

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY supervisor.py .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "supervisor:app", "--host", "0.0.0.0", "--port", "8000"]
