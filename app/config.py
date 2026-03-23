"""
Configuration management for AIEngine using Pydantic Settings.
Loads configuration from environment variables and .env file.
"""

import logging
import json
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    env: Literal["development", "staging", "production"] = Field(
        default="development", description="Environment mode"
    )
    log_level: str = Field(default="INFO", description="Logging level")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/aiengine.db",
        description="Database connection URL",
    )

    # Application
    # unknown url right now
    application_webhook_url: str = Field(
        default="onlyhuman.com",
        description="Webhook URL to POST facilitation messages back to application",
    )

    # Facilitation
    min_messages: int = Field(
        default=5,
        description="Minimum number of messages to start the facilitation",
    )

    limit_messages: int = Field(
        default=20, description="Number of messages retrieved from threads by default"
    )

    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key for LLM stages")

    # API Security
    api_key: str = Field(
        default="dev-api-key-change-in-production",
        description="API key for webhook authentication",
    )

    # ML Model
    model_path: str = Field(
        default="models/temporal_classifier.pkl",
        description="Path to pre-trained Random Forest model",
    )

    stage_2_model: str = Field(
        default="gpt-5-mini", description="OpenAI model to use for Stage-2"
    )
    stage_3_model: str = Field(
        default="gpt-4.1", description="OpenAI model to use for Stage-3"
    )
    stage_4_model: str = Field(
        default="gpt-5-mini", description="OpenAI model to use for Stage-4"
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging (used in production)."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%d %H:%M:%S"),
        }

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_logging(settings: Settings) -> None:
    """Configure logging based on environment."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Use JSON formatting in production, simple formatting in development
    if settings.env == "production":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Configure root logger
    logging.basicConfig(level=level, handlers=[handler])


# Global settings instance
settings = Settings()

# Setup logging on import
setup_logging(settings)
