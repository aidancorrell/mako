"""Configuration loaded from environment variables via pydantic-settings."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "MAKO_", "env_file": ".env"}

    # LLM providers
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    default_provider: str = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    claude_model: str = "claude-sonnet-4-20250514"

    # Paths
    workspace_path: Path = Path("workspace")

    # Security
    max_iterations: int = 10
    max_tool_calls_per_turn: int = 20
    max_tool_calls_per_minute: int = 30
    safe_bins_str: str = "curl,date"

    # Telegram (Phase 3)
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids_str: str = ""

    @property
    def safe_bins(self) -> list[str]:
        return [b.strip() for b in self.safe_bins_str.split(",") if b.strip()]

    @property
    def telegram_allowed_chat_ids(self) -> list[int]:
        if not self.telegram_allowed_chat_ids_str.strip():
            return []
        return [int(x.strip()) for x in self.telegram_allowed_chat_ids_str.split(",") if x.strip()]

    @field_validator("workspace_path", mode="after")
    @classmethod
    def resolve_workspace(cls, v: Path) -> Path:
        return v.resolve()


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
