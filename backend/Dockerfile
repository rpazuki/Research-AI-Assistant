FROM python:3.12-slim

WORKDIR /app

# System deps for torch and psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency install
RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system -e .

COPY . .

# Model cache is expected to be mounted as a volume in production
ENV EMBEDDING_CACHE_DIR=/app/model_cache

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
