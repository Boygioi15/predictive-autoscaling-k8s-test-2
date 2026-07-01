FROM node:18-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json ./
RUN npm install

COPY frontend ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=frontend-builder /frontend/dist ./frontend-dist

ENV PORT=8080
ENV SYSTEM_SHOWCASE_BASE_PATH=/system-showcase

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
