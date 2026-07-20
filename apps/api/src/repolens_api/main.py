"""FastAPI application entry point."""

from fastapi import FastAPI

from repolens_api import APP_NAME, SERVICE_NAME, __version__
from repolens_api.schemas import HealthResponse
from repolens_api.settings import get_settings

settings = get_settings()

app = FastAPI(
    title=APP_NAME,
    version=__version__,
    debug=settings.debug,
)


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API health",
    tags=["system"],
)
def get_health() -> HealthResponse:
    """Return the API's current health status."""
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=__version__,
    )
