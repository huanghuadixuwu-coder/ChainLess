FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

COPY . .

EXPOSE 9001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]
