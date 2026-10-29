from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DB_FULL_CONNECTION_STRING: str

    # Guardrails settings
    guardrails_backend: Literal["model_armor", "none"] = "none"

    # GCP / Vertex AI
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "us-central1"
    MODEL_ARMOR_TEMPLATE_ID: str = ""
    VERTEX_MODEL: str = "gemini-2.5-flash"

    # Langtrace observability
    # Optional: omit to run in local-only SQLite mode (no cloud upload)
    LANGTRACE_API_KEY: str | None = None
    # Set to true to print spans to stdout (useful during development)
    LANGTRACE_CONSOLE: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="allow")


# BaseSettings loads required values from the process environment or .env.
env = Env()  # pyright: ignore[reportCallIssue]
