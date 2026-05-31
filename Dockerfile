FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.6 \
    uvicorn[standard]==0.34.0 \
    pydantic==2.10.4 \
    pydantic-settings==2.7.1 \
    pandas==2.2.3 \
    numpy==2.2.1 \
    yfinance==0.2.52 \
    python-telegram-bot==21.10 \
    requests==2.32.3 \
    feedparser==6.0.11 \
    apscheduler==3.10.4 \
    rich==13.9.4 \
    jinja2==3.1.5 \
    && rm -rf /root/.cache/pip

COPY . .

EXPOSE 8000

CMD ["python", "main.py", "web"]
