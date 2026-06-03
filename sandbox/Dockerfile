FROM python:3.10-slim
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple httpx requests
RUN useradd -m -u 1000 sandbox
WORKDIR /workspace
RUN chown sandbox:sandbox /workspace
COPY runner.py /runner.py
USER sandbox
