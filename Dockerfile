FROM python:3.14-slim-bookworm

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY models/ ./models/
COPY services/ ./services/
COPY utils.py handler.py ./
RUN uv sync --frozen --no-dev

RUN uv run playwright install --with-deps chromium

RUN apt-get update && apt-get install -y --no-install-recommends xvfb x11-utils && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV LOG_LEVEL=INFO
ENV USERS_FILE=/config/users.yaml

ENTRYPOINT ["./entrypoint.sh"]
