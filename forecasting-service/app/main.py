from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from .config import settings
from .models import ForecastRequest, ForecastResponse
from .service import ForecastingService

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
service = ForecastingService()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/forecast", response_model=ForecastResponse)
async def forecast(request: ForecastRequest) -> ForecastResponse:
    logger.info("Received /forecast payload=%s", request.model_dump_json())
    return await service.predict_workload(request)


@app.post("/predict-workload", response_model=ForecastResponse)
async def predict_workload(request: ForecastRequest) -> ForecastResponse:
    logger.info("Received /predict-workload payload=%s", request.model_dump_json())
    return await service.predict_workload(request)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "forecasting-service is running"}
