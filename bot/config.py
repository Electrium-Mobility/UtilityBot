import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Bot settings loaded from environment variables."""
    token: str


def load_settings() -> Settings:
    """Load settings from environment variables."""
    token = os.getenv("DISCORD_TOKEN", "")
    return Settings(token=token)


settings = load_settings()