FROM python:3.11-slim
WORKDIR /app
COPY libs /app/libs
COPY services/ai-admin-service /app/svc
RUN pip install --no-cache-dir -r /app/svc/requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/libs
WORKDIR /app/svc
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8800"]
