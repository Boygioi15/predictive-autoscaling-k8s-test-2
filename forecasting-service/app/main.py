from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .models import PredictionRequest, PredictionResponse
from .service import ForecastingService


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
service = ForecastingService()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/predict-workload", response_model=PredictionResponse)
async def predict_workload(request: PredictionRequest) -> PredictionResponse:
    return await service.predict_workload(request)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "forecasting-service is running"}
