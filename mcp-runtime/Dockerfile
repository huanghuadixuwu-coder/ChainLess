FROM python:3.10-slim

RUN useradd --create-home --uid 10001 runtime

WORKDIR /runtime

COPY requirements.txt /runtime/requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /runtime/requirements.txt

COPY runtime_service.py echo_mcp_server.py /runtime/

USER runtime

EXPOSE 9101

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9101/health', timeout=2).read()"

CMD ["uvicorn", "runtime_service:app", "--host", "0.0.0.0", "--port", "9101"]
