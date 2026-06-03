FROM python:3.10-slim

WORKDIR /app

# Use Tsinghua mirror for faster downloads in China
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi \
    "uvicorn[standard]" \
    sqlalchemy \
    asyncpg \
    alembic \
    pydantic-settings \
    httpx \
    openai \
    redis \
    arq \
    docker \
    python-jose \
    "passlib[bcrypt]" \
    "bcrypt>=4.0.0,<5.0.0" \
    python-multipart \
    litellm \
    pgvector \
    tiktoken \
    mcp \
    croniter

COPY . .

RUN chmod +x scripts/startup.sh scripts/seed.py

EXPOSE 8000

CMD ["./scripts/startup.sh"]
