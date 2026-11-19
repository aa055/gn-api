FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# `docker build --target test .` stops here, and fails if any test fails
FROM base AS test
COPY tests ./tests
RUN python -m pytest -q

# Last stage, so a plain `docker build -t app .` builds the server
FROM base AS runtime
EXPOSE 8080
# One worker on purpose: all data lives in this process's memory
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
