"""
FastAPI application entry point for AIEngine.
Multi-stage chat facilitation AI system for Alzheimer's caregiver support groups.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.database import init_db
from app.api.routes import health, messages

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup
    logger.info("Starting AIEngine application...")
    logger.info(f"Environment: {settings.env}")
    logger.info(f"Database URL: {settings.database_url}")

    # Initialize database tables
    await init_db()
    logger.info("Database initialized successfully")

    yield

    # Shutdown
    logger.info("Shutting down AIEngine application...")


# Create FastAPI application
app = FastAPI(
    title="AIEngine",
    description="Multi-stage chat facilitation AI system for Alzheimer's caregiver support groups",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url="/redoc" if settings.env != "production" else None,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    # Change production origins to only-human server domains
    allow_origins=["*"] if settings.env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(messages.router)
# app.include_router(facilitation.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "AIEngine",
        "version": "1.0.0",
        "description": "Multi-stage chat facilitation AI system",
        "status": "running"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=(settings.env == "development"),
        log_level=settings.log_level.lower()
    )
