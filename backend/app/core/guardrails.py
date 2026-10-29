"""Backend-agnostic guardrails integration.

Provides a unified interface for prompt injection detection, content compliance,
and sensitive-data-leak prevention. Supports multiple backends via a pluggable
architecture.

Configuration:
  env (see ``app.core.env``):
    guardrails_backend       – backend to use: 'openguardrails' | 'model_armor' | 'none'
    openguardrails_api_key   – (OpenGuardrails) API key (secret – env only)
    GCP_PROJECT_ID           – (Model Armor) GCP project ID
    GCP_LOCATION             – (Model Armor) GCP region, e.g. 'us-central1'
    MODEL_ARMOR_TEMPLATE_ID  – (Model Armor) template identifier
  app/core/open_guardrails/filter_config.yaml:
    client.base_url          – (OpenGuardrails) endpoint URL
    client.timeout           – (OpenGuardrails) timeout in seconds
    client.max_retries       – (OpenGuardrails) retry count
  app/core/model_armor/filter_config.yaml:
    filter_config            – (Model Armor) RAI and PI/jailbreak filter settings

Usage (sync)::

    from app.core.guardrails import guardrails
    result = guardrails.check_prompt("user input here", user_id="user-123")
    if result.is_blocked:
        # handle blocked content

Usage (async)::

    from app.core.guardrails import async_guardrails
    async with async_guardrails() as client:
        result = await client.check_prompt("user input here")
        if result.is_blocked:
            # handle blocked content
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pathlib

import yaml

from app.core.env import env
from app.core.logger import app_logger

_FILTER_CONFIG_PATH = (
    pathlib.Path(__file__).parent / "open_guardrails" / "filter_config.yaml"
)


# ---------------------------------------------------------------------------
# Filter configuration
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class FilterConfig:
    """Filter/policy options loaded from filter_config.yaml.

    Only the API key is a secret and comes from the environment.
    Everything else (connection settings, detector options) lives in
    filter_config.yaml and is safe to commit to version control.
    """

    # Client connection settings
    base_url: str = "https://api.openguardrails.com/v1"
    timeout: int = 30
    max_retries: int = 3

    @classmethod
    def from_yaml(cls, path: pathlib.Path = _FILTER_CONFIG_PATH) -> "FilterConfig":
        """Load filter options from *path*, falling back to defaults if absent."""
        if not path.exists():
            return cls()
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}

        client_cfg = cfg.get("client", {})

        return cls(
            base_url=client_cfg.get("base_url", cls.base_url),
            timeout=client_cfg.get("timeout", cls.timeout),
            max_retries=client_cfg.get("max_retries", cls.max_retries),
        )


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------


class GuardrailResponse:
    """Unified response object for guardrail checks."""

    def __init__(
        self,
        suggest_action: str,
        overall_risk_level: str,
        is_safe: bool,
        is_blocked: bool,
        score: float = 0.0,
        raw_response: Any = None,
    ):
        self.suggest_action = suggest_action
        self.overall_risk_level = overall_risk_level
        self._is_safe = is_safe
        self._is_blocked = is_blocked
        self.score = score
        self.raw_response = raw_response

    @property
    def is_safe(self) -> bool:
        return self._is_safe

    @property
    def is_blocked(self) -> bool:
        return self._is_blocked


class BaseGuardrails(ABC):
    """Abstract base class for guardrail providers."""

    @abstractmethod
    def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        """Check the safety of a single prompt (synchronous)."""
        pass

    @abstractmethod
    def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        """Check conversation context safety (synchronous)."""
        pass


class BaseAsyncGuardrails(ABC):
    """Abstract base class for async guardrail providers."""

    @abstractmethod
    async def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        """Check the safety of a single prompt (asynchronous)."""
        pass

    @abstractmethod
    async def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        """Check conversation context safety (asynchronous)."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close async resources."""
        pass


# ---------------------------------------------------------------------------
# OpenGuardrails implementation
# ---------------------------------------------------------------------------


class OpenGuardrailsProvider(BaseGuardrails):
    """OpenGuardrails sync provider — wraps OpenGuardrailsClient."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        try:
            from app.core.open_guardrails.open_guardrails import OpenGuardrailsClient
        except ImportError as e:
            raise ImportError(
                "openguardrails package not found. "
                "Install it with: uv sync --extra guardrails"
            ) from e
        self.client = OpenGuardrailsClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        result = self.client.check_prompt(content, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            score=result.score,
            raw_response=result.raw_response,
        )

    def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        result = self.client.check_conversation(messages, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            score=result.score,
            raw_response=result.raw_response,
        )


class AsyncOpenGuardrailsProvider(BaseAsyncGuardrails):
    """OpenGuardrails async provider — wraps AsyncOpenGuardrailsClient."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        try:
            from app.core.open_guardrails.open_guardrails import AsyncOpenGuardrailsClient
        except ImportError as e:
            raise ImportError(
                "openguardrails package not found. "
                "Install it with: uv sync --extra guardrails"
            ) from e
        self.client = AsyncOpenGuardrailsClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        result = await self.client.check_prompt(content, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            score=result.score,
            raw_response=result.raw_response,
        )

    async def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        result = await self.client.check_conversation(messages, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            score=result.score,
            raw_response=result.raw_response,
        )

    async def close(self) -> None:
        await self.client.close()


# ---------------------------------------------------------------------------
# Google Cloud Model Armor implementation
# ---------------------------------------------------------------------------


class ModelArmorProvider(BaseGuardrails):
    """Google Cloud Model Armor sync provider."""

    def __init__(self, project_id: str, location: str, template_id: str) -> None:
        try:
            from app.core.model_armor.model_armor import ModelArmorClient
        except ImportError as e:
            raise ImportError(
                "google-cloud-modelarmor is not installed. "
                "Add it to your dependencies: google-cloud-modelarmor>=0.5.0"
            ) from e
        self.client = ModelArmorClient(project_id, location, template_id)

    def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        result = self.client.check_prompt(content, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            raw_response=result.raw_response,
        )

    def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        result = self.client.check_conversation(messages, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            raw_response=result.raw_response,
        )


class AsyncModelArmorProvider(BaseAsyncGuardrails):
    """Google Cloud Model Armor async provider."""

    def __init__(self, project_id: str, location: str, template_id: str) -> None:
        try:
            from app.core.model_armor.model_armor import AsyncModelArmorClient
        except ImportError as e:
            raise ImportError(
                "google-cloud-modelarmor is not installed. "
                "Add it to your dependencies: google-cloud-modelarmor>=0.5.0"
            ) from e
        self.client = AsyncModelArmorClient(project_id, location, template_id)

    async def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        result = await self.client.check_prompt(content, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            raw_response=result.raw_response,
        )

    async def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        result = await self.client.check_conversation(messages, user_id=user_id)
        return GuardrailResponse(
            suggest_action=result.suggest_action,
            overall_risk_level=result.overall_risk_level,
            is_safe=result.is_safe,
            is_blocked=result.is_blocked,
            raw_response=result.raw_response,
        )

    async def close(self) -> None:
        await self.client.close()


# ---------------------------------------------------------------------------
# No-op implementation (when guardrails are disabled)
# ---------------------------------------------------------------------------


class NoOpGuardrails(BaseGuardrails):
    """No-op implementation that always passes."""

    def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        return GuardrailResponse(
            suggest_action="pass",
            overall_risk_level="no_risk",
            is_safe=True,
            is_blocked=False,
            score=1.0,
        )

    def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        return GuardrailResponse(
            suggest_action="pass",
            overall_risk_level="no_risk",
            is_safe=True,
            is_blocked=False,
            score=1.0,
        )


class AsyncNoOpGuardrails(BaseAsyncGuardrails):
    """Async no-op implementation that always passes."""

    async def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> GuardrailResponse:
        return GuardrailResponse(
            suggest_action="pass",
            overall_risk_level="no_risk",
            is_safe=True,
            is_blocked=False,
            score=1.0,
        )

    async def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> GuardrailResponse:
        return GuardrailResponse(
            suggest_action="pass",
            overall_risk_level="no_risk",
            is_safe=True,
            is_blocked=False,
            score=1.0,
        )

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def _create_guardrails_client() -> BaseGuardrails:
    """Create sync guardrails client based on env config."""
    backend = env.guardrails_backend

    if backend == "openguardrails":
        _cfg = FilterConfig.from_yaml()
        app_logger.info(
            "Initialising OpenGuardrails sync client (base_url={})",
            _cfg.base_url,
        )
        return OpenGuardrailsProvider(
            api_key=env.openguardrails_api_key,
            base_url=_cfg.base_url,
            timeout=_cfg.timeout,
            max_retries=_cfg.max_retries,
        )
    elif backend == "model_armor":
        app_logger.info(
            "Initialising Model Armor sync client (project={}, location={}, template={})",
            env.GCP_PROJECT_ID,
            env.GCP_LOCATION,
            env.MODEL_ARMOR_TEMPLATE_ID,
        )
        return ModelArmorProvider(
            project_id=env.GCP_PROJECT_ID,
            location=env.GCP_LOCATION,
            template_id=env.MODEL_ARMOR_TEMPLATE_ID,
        )
    elif backend == "none":
        app_logger.info("Guardrails disabled (using no-op provider)")
        return NoOpGuardrails()
    else:
        app_logger.warning(
            "Unknown guardrails backend '{}', falling back to no-op", backend
        )
        return NoOpGuardrails()


# ---------------------------------------------------------------------------
# Sync client – importable singleton
# ---------------------------------------------------------------------------

guardrails = _create_guardrails_client()

# ---------------------------------------------------------------------------
# Async client – use as an async context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def async_guardrails() -> AsyncGenerator[BaseAsyncGuardrails]:
    """Yield an async guardrails client that auto-closes on exit.

    Example::

        async with async_guardrails() as client:
            result = await client.check_prompt("some text")
            if result.is_blocked:
                raise HTTPException(400, detail="Content blocked")
    """
    backend = env.guardrails_backend

    if backend == "openguardrails":
        _cfg = FilterConfig.from_yaml()
        client: BaseAsyncGuardrails = AsyncOpenGuardrailsProvider(
            api_key=env.openguardrails_api_key,
            base_url=_cfg.base_url,
            timeout=_cfg.timeout,
            max_retries=_cfg.max_retries,
        )
    elif backend == "model_armor":
        client = AsyncModelArmorProvider(
            project_id=env.GCP_PROJECT_ID,
            location=env.GCP_LOCATION,
            template_id=env.MODEL_ARMOR_TEMPLATE_ID,
        )
    elif backend == "none":
        client = AsyncNoOpGuardrails()
    else:
        app_logger.warning(
            "Unknown guardrails backend '{}', falling back to no-op", backend
        )
        client = AsyncNoOpGuardrails()

    try:
        yield client
    finally:
        await client.close()
