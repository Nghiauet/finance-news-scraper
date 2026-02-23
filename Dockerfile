FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first (cached layer — only rebuilds when lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source
COPY . .

# Install the project itself
RUN uv sync --frozen --no-dev

EXPOSE 46401

CMD ["uv", "run", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "46401"]
