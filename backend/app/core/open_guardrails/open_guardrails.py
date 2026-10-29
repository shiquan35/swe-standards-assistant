"""OpenGuardrails SDK client.

Provides SDK-like client classes (``OpenGuardrailsClient`` and
``AsyncOpenGuardrailsClient``) that implement the same interface expected by
``app.core.guardrails`` providers.

The filter_config.yaml in this folder stores connection settings (base_url,
timeout, max_retries). The API key is a secret and must come from the
environment.

Client classes (used by guardrails.py providers):
    OpenGuardrailsClient      – sync, returns OpenGuardrailsResult
    AsyncOpenGuardrailsClient – async, closes with await client.close()
"""

from __future__ import annotations

import dataclasses
import pathlib
import yaml
from typing import Any

_FILTER_CONFIG_PATH = pathlib.Path(__file__).parent / "filter_config.yaml"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OpenGuardrailsResult:
    """Normalised result from an OpenGuardrails check.

    Mirrors the field shape used by ``GuardrailResponse`` in
    ``app.core.guardrails`` so providers can map it without coupling to the
    SDK response type directly.
    """

    is_blocked: bool
    is_safe: bool
    suggest_action: str
    overall_risk_level: str
    score: float = 0.0
    raw_response: Any = None


# ---------------------------------------------------------------------------
# Filter configuration helper
# ---------------------------------------------------------------------------


def load_filter_config(path: pathlib.Path = _FILTER_CONFIG_PATH) -> dict:
    """Load connection settings from filter_config.yaml.

    Returns an empty dict if the file does not exist, so callers can
    fall back to defaults without error.
    """
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# SDK-like client classes (consumed by app.core.guardrails providers)
# ---------------------------------------------------------------------------


class OpenGuardrailsClient:
    """Synchronous OpenGuardrails client with a guardrails-compatible interface.

    Usage::

        client = OpenGuardrailsClient(api_key, base_url, timeout, max_retries)
        result = client.check_prompt("user input")
        if result.is_blocked:
            ...
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openguardrails.com/v1",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._sdk_client: Any = None

    @property
    def _client(self) -> Any:
        """Lazily initialise the underlying SDK client."""
        if self._sdk_client is None:
            try:
                from openguardrails import OpenGuardrails
            except ImportError as e:
                raise ImportError(
                    "openguardrails package not found. "
                    "Install it with: uv sync --extra guardrails"
                ) from e
            self._sdk_client = OpenGuardrails(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        return self._sdk_client

    def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> OpenGuardrailsResult:
        """Check a single prompt and return a normalised result."""
        result = self._client.check_prompt(content, user_id=user_id)
        return OpenGuardrailsResult(
            is_blocked=result.is_blocked,
            is_safe=result.is_safe,
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            score=result.score,
            raw_response=result,
        )

    def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> OpenGuardrailsResult:
        """Check full conversation context and return a normalised result."""
        result = self._client.check_conversation(messages, user_id=user_id)
        return OpenGuardrailsResult(
            is_blocked=result.is_blocked,
            is_safe=result.is_safe,
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            score=result.score,
            raw_response=result,
        )


class AsyncOpenGuardrailsClient:
    """Asynchronous OpenGuardrails client with a guardrails-compatible interface.

    Unlike the Model Armor async client (which uses ``asyncio.to_thread``),
    this client uses the native async OpenGuardrails SDK directly.

    Usage::

        client = AsyncOpenGuardrailsClient(api_key, base_url, timeout, max_retries)
        result = await client.check_prompt("user input")
        if result.is_blocked:
            ...
        await client.close()
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openguardrails.com/v1",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._sdk_client: Any = None

    @property
    def _client(self) -> Any:
        """Lazily initialise the underlying async SDK client."""
        if self._sdk_client is None:
            try:
                from openguardrails import AsyncOpenGuardrails
            except ImportError as e:
                raise ImportError(
                    "openguardrails package not found. "
                    "Install it with: uv sync --extra guardrails"
                ) from e
            self._sdk_client = AsyncOpenGuardrails(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        return self._sdk_client

    async def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> OpenGuardrailsResult:
        """Check a single prompt and return a normalised result."""
        result = await self._client.check_prompt(content, user_id=user_id)
        return OpenGuardrailsResult(
            is_blocked=result.is_blocked,
            is_safe=result.is_safe,
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            score=result.score,
            raw_response=result,
        )

    async def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> OpenGuardrailsResult:
        """Check full conversation context and return a normalised result."""
        result = await self._client.check_conversation(messages, user_id=user_id)
        return OpenGuardrailsResult(
            is_blocked=result.is_blocked,
            is_safe=result.is_safe,
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            score=result.score,
            raw_response=result,
        )

    async def close(self) -> None:
        """Close the underlying async SDK client."""
        if self._sdk_client is not None:
            await self._sdk_client.close()


# ---------------------------------------------------------------------------
# Script entry-point (quick smoke-test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging
    import os
    import time

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    api_key = os.getenv("OPENGUARDRAILS_API_KEY", "")
    if not api_key:
        raise ValueError("OPENGUARDRAILS_API_KEY environment variable is required.")

    cfg = load_filter_config()
    client_cfg = cfg.get("client", {})

    client = OpenGuardrailsClient(
        api_key=api_key,
        base_url=client_cfg.get("base_url", "https://api.openguardrails.com/v1"),
        timeout=client_cfg.get("timeout", 30),
        max_retries=client_cfg.get("max_retries", 3),
    )

    try:
        start = time.time()
        result = client.check_prompt("How are you doing today?", user_id="smoke-test")
        latency_ms = (time.time() - start) * 1000

        logging.info(f"✅ Prompt check completed ({latency_ms:.2f}ms)")
        logging.info(f"   is_safe:            {result.is_safe}")
        logging.info(f"   is_blocked:         {result.is_blocked}")
        logging.info(f"   overall_risk_level: {result.overall_risk_level}")
        logging.info(f"   suggest_action:     {result.suggest_action}")
        logging.info(f"   score:              {result.score}")
    except Exception as e:
        print(f"❌ Failed: {e}")
