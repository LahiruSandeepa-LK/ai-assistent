FROM python:3.11-slim
WORKDIR /app
COPY services/ui-admin /app
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1
CMD ["streamlit","run","app.py","--server.port=8502","--server.address=0.0.0.0"]
