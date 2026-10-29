from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DB_FULL_CONNECTION_STRING: str

    # Guardrails settings
    guardrails_backend: Literal["openguardrails", "model_armor", "none"] = "none"
    # OpenGuardrails – connection options (base_url, timeout, retries) live in filter_config.yaml
    openguardrails_api_key: str = ""

    # GCP / Vertex AI
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "us-central1"
    MODEL_ARMOR_TEMPLATE_ID: str = ""
    VERTEX_MODEL: str = "gemini-2.5-flash"

    # Langtrace observability
    # Optional: omit to run in local-only SQLite mode (no cloud upload)
    LANGTRACE_API_KEY: str | None
    # Set to true to print spans to stdout (useful during development)
    LANGTRACE_CONSOLE: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="allow")


env = Env()
