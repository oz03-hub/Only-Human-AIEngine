"""
Configuration settings for the facilitation module.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Configuration settings for the facilitation pipeline."""

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1")
    model_path: str = os.getenv("MODEL_PATH", "models/temporal_classifier.pkl")


settings = Settings()
