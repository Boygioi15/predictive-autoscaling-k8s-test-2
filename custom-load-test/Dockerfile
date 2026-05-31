FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY workload.py /app/workload.py
COPY load_sender.py /app/load_sender.py

CMD ["python", "-u", "/app/load_sender.py"]
