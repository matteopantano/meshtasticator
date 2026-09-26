FROM python:3.11-slim

WORKDIR /app

COPY meshtastic-web-gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY meshtastic-web-gateway/app ./app
COPY meshtasticd-config /workspace/meshtasticd-config

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
