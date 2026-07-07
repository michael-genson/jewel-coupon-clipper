FROM python:3.14-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY models/ ./models/
COPY services/ ./services/
COPY utils.py handler.py ./
RUN uv sync --frozen --no-dev

RUN uv run playwright install-deps firefox
RUN uv run python -m invisible_playwright fetch

ENV LOG_LEVEL=INFO
ENV USERS_FILE=/config/users.yaml

ENTRYPOINT ["uv", "run", "python", "handler.py"]
