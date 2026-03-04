FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./src/fetch-prometheus-data.py .
RUN mkdir -p data

CMD ["python", "./src/fetch-prometheus-data.py"]
