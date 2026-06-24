FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN mkdir -p /app/scripts /app/output

COPY custom_load_generator.env /app/custom_load_generator.env
COPY workload.py /app/workload.py
COPY load_sender.py /app/load_sender.py
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
COPY scripts /app/scripts

RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
