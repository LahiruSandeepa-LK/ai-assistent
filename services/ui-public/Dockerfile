FROM python:3.11-slim
WORKDIR /app
COPY services/ui-public /app
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1
CMD ["streamlit","run","app.py","--server.port=8501","--server.address=0.0.0.0"]
