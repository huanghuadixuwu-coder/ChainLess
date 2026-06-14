FROM python:3.10-slim
ARG SUBAGENT_CONTROL_GID=10001
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple httpx requests
RUN groupadd -g ${SUBAGENT_CONTROL_GID} subagent-control \
    && useradd -m -u 1000 sandbox
WORKDIR /workspace
RUN chown sandbox:sandbox /workspace
COPY runner.py /runner.py
USER sandbox
