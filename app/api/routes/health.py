"""
Health check endpoint for monitoring and readiness checks.
"""

from datetime import datetime
from fastapi import APIRouter

from app.models.schemas import HealthCheckResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """
    Health check endpoint.
    Returns system status and version information.
    No authentication required.
    """
    return HealthCheckResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="1.0.0"
    )
