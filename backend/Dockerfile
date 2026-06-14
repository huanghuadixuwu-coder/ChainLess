FROM python:3.10-slim

WORKDIR /app

RUN sed -i \
        -e 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        -e 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY . .

ARG INSTALL_TEST_DEPS=0

# Use Tsinghua mirror for faster downloads in China.
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
        -r requirements.txt \
    && if [ "$INSTALL_TEST_DEPS" = "1" ]; then \
        pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
            -r requirements-test.txt; \
    fi

RUN sed -i 's/\r$//' scripts/startup.sh scripts/backup.sh scripts/restore.sh \
    && chmod +x scripts/startup.sh scripts/seed.py scripts/backup.sh scripts/restore.sh scripts/clean_start_probe.py

EXPOSE 8000

CMD ["./scripts/startup.sh"]
