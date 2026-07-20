"""HTTP response models exposed by the API."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Successful health-check response."""

    status: Literal["ok"]
    service: str
    version: str
