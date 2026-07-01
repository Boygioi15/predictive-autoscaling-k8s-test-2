from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .settings import settings
from .snapshot_service import snapshot_service


class LoadTestScriptRequest(BaseModel):
    filename: str = Field(min_length=1)
    content: str = Field(min_length=1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await snapshot_service.start_background_poller()
    try:
        yield
    finally:
        await snapshot_service.stop_background_poller()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
base_path = settings.normalized_base_path
frontend_dist_dir = settings.frontend_dist_dir
assets_dir = frontend_dist_dir / "assets"

if assets_dir.exists():
    app.mount(f"{base_path}/assets", StaticFiles(directory=str(assets_dir)), name="system-showcase-assets")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url=f"{base_path}/", status_code=307)


@app.get(base_path, include_in_schema=False)
async def base_redirect() -> RedirectResponse:
    return RedirectResponse(url=f"{base_path}/", status_code=307)


@app.get(f"{base_path}/", include_in_schema=False)
async def showcase_home() -> Response:
    index_path = frontend_dist_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        "<h1>system-showcase frontend has not been built yet.</h1>"
        "<p>Run the frontend build or build the Docker image to generate the static assets.</p>",
        status_code=503,
    )


@app.get(f"{base_path}/api/health")
async def showcase_api_health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get(f"{base_path}/api/snapshot")
async def showcase_snapshot(
    force_refresh: bool = Query(default=False, alias="forceRefresh"),
    scaler_namespace: str | None = Query(default=None, alias="scalerNamespace"),
    scaler_name: str | None = Query(default=None, alias="scalerName"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, alias="pageSize", ge=1, le=100),
) -> dict[str, Any]:
    return await snapshot_service.get_snapshot(
        force_refresh=force_refresh,
        scaler_namespace=scaler_namespace,
        scaler_name=scaler_name,
        page=page,
        page_size=page_size,
    )


@app.get(f"{base_path}/api/load-test")
async def get_load_test_state() -> dict[str, Any]:
    return snapshot_service.get_load_test()


@app.get(f"{base_path}/api/script-range")
async def get_script_range(
    real_start: datetime | None = Query(default=None, alias="realStart"),
    world_cup_start: datetime | None = Query(default=None, alias="worldCupStart"),
    duration_seconds: int | None = Query(default=None, alias="durationSeconds", ge=1, le=604800),
) -> dict[str, Any]:
    return await snapshot_service.get_script_range(
        real_start=real_start,
        world_cup_start=world_cup_start,
        duration_seconds=duration_seconds,
    )


@app.post(f"{base_path}/api/load-test/script")
async def save_load_test_script(payload: LoadTestScriptRequest) -> dict[str, Any]:
    return snapshot_service.save_load_test_script(
        filename=payload.filename,
        content=payload.content,
    )


@app.post(f"{base_path}/api/load-test/metadata")
async def save_load_test_metadata(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return snapshot_service.save_load_test_metadata(payload)
