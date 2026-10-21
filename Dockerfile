FROM python:3.12-slim
WORKDIR /app
# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
# Copy project files
COPY pyproject.toml uv.lock ./
COPY src ./src
# Install dependencies
RUN uv sync --frozen --no-dev
ENV PYTHONPATH=/app/src
CMD ["uv", "run", "uvicorn", "crucible.sandbox.app:app", "--host", "0.0.0.0", "--port", "8000"]