FROM python:3.11-slim
WORKDIR /app
COPY libs /app/libs
COPY services/ui-admin /app/svc
RUN pip install --no-cache-dir -r /app/svc/requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/libs
WORKDIR /app/svc
CMD ["streamlit","run","app.py","--server.port=8502","--server.address=0.0.0.0"]
