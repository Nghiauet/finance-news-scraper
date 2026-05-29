# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
ARG VITE_BASE_PATH=/portal/
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
WORKDIR /frontend
COPY portal/package.json portal/package-lock.json ./
RUN npm ci
COPY portal/ ./
RUN npm run build

# Stage 2: Python API + built frontend
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

# Copy built frontend
COPY --from=frontend-builder /frontend/dist portal_dist/

EXPOSE 46401

CMD ["uv", "run", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "46401"]
