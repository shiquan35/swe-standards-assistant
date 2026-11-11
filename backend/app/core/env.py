from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DB_FULL_CONNECTION_STRING: str

    # Embedding credentials are required only when making an uncached request.
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_EMBEDDING_MODEL: Literal["text-embedding-3-small"] = "text-embedding-3-small"

    # Single-turn generation budgets; model/tokenizer compatibility is checked by RAG.
    OPENAI_CHAT_MODEL: str = "gpt-6-luna"
    RAG_MAX_INPUT_TOKENS: int = Field(default=32000, gt=0)
    RAG_MAX_OUTPUT_TOKENS: int = Field(default=4096, gt=0)
    RAG_TOKEN_SAFETY_MARGIN: float = Field(default=0.20, ge=0, le=1)
    # Operator-known model limit, not inferred from the model name.
    RAG_MODEL_CONTEXT_WINDOW: int = Field(default=1050000, gt=0)

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
