"""Google Cloud Model Armor guardrails client.

Exposes low-level helper functions for template management and prompt
sanitization, plus two SDK-like client classes (``ModelArmorClient`` and
``AsyncModelArmorClient``) that implement the same interface expected by
``app.core.guardrails`` providers.

Low-level helpers (for direct use / scripts):
    init(location)              – create a raw API client
    create_template(client)     – create a filtering template
    delete_template(client, id) – remove a template
    get_template(client, id)    – retrieve a template
    sanitize_prompt(client, text) – sanitize a single prompt

Client classes (used by guardrails.py providers):
    ModelArmorClient      – sync, returns ModelArmorResult
    AsyncModelArmorClient – async wrapper via asyncio.to_thread
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
import yaml
from typing import Any

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback: manual .env loading if python-dotenv is not installed
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

# Module-level convenience references (used by low-level helpers and __main__)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_LOCATION")
MODEL_ARMOR_TEMPLATE_ID = os.getenv("MODEL_ARMOR_TEMPLATE_ID")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ModelArmorResult:
    """Normalised result from a Model Armor sanitization check.

    Mirrors the field shape used by ``GuardrailResponse`` in
    ``app.core.guardrails`` so providers can map it without importing
    google-cloud-modelarmor themselves.
    """

    is_blocked: bool
    is_safe: bool
    suggest_action: str
    overall_risk_level: str
    raw_response: Any = None


# ---------------------------------------------------------------------------
# Filter configuration helper
# ---------------------------------------------------------------------------


def load_filter_config() -> dict:
    """Load filter configuration from filter_config.yaml."""
    config_file = os.path.join(os.path.dirname(__file__), 'filter_config.yaml')
    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_api_client(location: str) -> Any:
    """Construct a ``modelarmor_v1.ModelArmorClient`` for *location*."""
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import modelarmor_v1
    except ImportError as e:
        raise ImportError(
            "google-cloud-modelarmor is not installed. "
            "Add it to your dependencies: google-cloud-modelarmor>=0.5.0"
        ) from e

    api_endpoint = f"modelarmor.{location}.rep.googleapis.com"
    return modelarmor_v1.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(api_endpoint=api_endpoint),
    )


def _map_sanitize_response(response: Any) -> ModelArmorResult:
    """Map a ``SanitizeUserPromptResponse`` to ``ModelArmorResult``."""
    from google.cloud import modelarmor_v1

    match_state = response.sanitization_result.filter_match_state
    is_blocked = match_state == modelarmor_v1.FilterMatchState.MATCH_FOUND
    return ModelArmorResult(
        is_blocked=is_blocked,
        is_safe=not is_blocked,
        suggest_action="block" if is_blocked else "pass",
        overall_risk_level="high" if is_blocked else "no_risk",
        raw_response=response,
    )


# ---------------------------------------------------------------------------
# Low-level helper functions (backward-compatible public API)
# ---------------------------------------------------------------------------


def init(location: str | None = None) -> Any:
    """Initialize and return a raw Model Armor API client.

    Args:
        location: GCP region (defaults to the ``GCP_LOCATION`` env var).
    """
    _location = location or GCP_LOCATION
    if not _location:
        raise ValueError("location must be provided or GCP_LOCATION must be set")
    print(f"🔧 Initializing Model Armor client (location={_location})")
    return _build_api_client(_location)


def create_template(
    client: Any,
    project_id: str | None = None,
    location: str | None = None,
    template_id: str | None = None,
) -> str:
    """Create a Model Armor template using settings from filter_config.yaml.

    Args:
        client:      A ``modelarmor_v1.ModelArmorClient`` instance.
        project_id:  GCP project (defaults to ``GCP_PROJECT_ID`` env var).
        location:    GCP region (defaults to ``GCP_LOCATION`` env var).
        template_id: Template identifier (defaults to ``MODEL_ARMOR_TEMPLATE_ID``).

    Returns:
        The fully-qualified name of the created template.
    """
    from google.cloud import modelarmor_v1

    _project_id = project_id or GCP_PROJECT_ID
    _location = location or GCP_LOCATION
    _template_id = template_id or MODEL_ARMOR_TEMPLATE_ID

    if not all([_project_id, _location, _template_id]):
        raise ValueError("project_id, location, and template_id are required")

    config = load_filter_config()
    filter_config = config['filter_config']

    rai_filters = []
    for rai_filter in filter_config['rai_settings']['rai_filters']:
        filter_type = getattr(modelarmor_v1.RaiFilterType, rai_filter['filter_type'])
        confidence_level = getattr(modelarmor_v1.DetectionConfidenceLevel, rai_filter['confidence_level'])
        rai_filters.append(
            modelarmor_v1.RaiFilterSettings.RaiFilter(
                filter_type=filter_type,
                confidence_level=confidence_level,
            )
        )

    pi_jailbreak_settings = filter_config['pi_and_jailbreak_settings']
    filter_enforcement = getattr(
        modelarmor_v1.PiAndJailbreakFilterSettings.PiAndJailbreakFilterEnforcement,
        pi_jailbreak_settings['filter_enforcement'],
    )
    pi_confidence_level = getattr(
        modelarmor_v1.DetectionConfidenceLevel,
        pi_jailbreak_settings['confidence_level'],
    )

    template = modelarmor_v1.Template(
        filter_config=modelarmor_v1.FilterConfig(
            rai_settings=modelarmor_v1.RaiFilterSettings(rai_filters=rai_filters),
            pi_and_jailbreak_filter_settings=modelarmor_v1.PiAndJailbreakFilterSettings(
                filter_enforcement=filter_enforcement,
                confidence_level=pi_confidence_level,
            ),
        )
    )

    request = modelarmor_v1.CreateTemplateRequest(
        parent=f"projects/{_project_id}/locations/{_location}",
        template_id=_template_id,
        template=template,
    )

    response = client.create_template(request=request)
    return response.name


def delete_template(
    client: Any,
    template_name: str,
    project_id: str | None = None,
    location: str | None = None,
) -> None:
    """Delete a Model Armor template by name.

    Args:
        client:        A ``modelarmor_v1.ModelArmorClient`` instance.
        template_name: The short template ID or fully-qualified name.
        project_id:    GCP project (defaults to ``GCP_PROJECT_ID`` env var).
        location:      GCP region (defaults to ``GCP_LOCATION`` env var).
    """
    from google.cloud import modelarmor_v1

    _project_id = project_id or GCP_PROJECT_ID
    _location = location or GCP_LOCATION

    request = modelarmor_v1.DeleteTemplateRequest(
        name=f"projects/{_project_id}/locations/{_location}/templates/{template_name}"
    )
    client.delete_template(request=request)


def get_template(
    client: Any,
    template_name: str,
    project_id: str | None = None,
    location: str | None = None,
) -> Any:
    """Retrieve a Model Armor template by name.

    Args:
        client:        A ``modelarmor_v1.ModelArmorClient`` instance.
        template_name: The short template ID or fully-qualified name.
        project_id:    GCP project (defaults to ``GCP_PROJECT_ID`` env var).
        location:      GCP region (defaults to ``GCP_LOCATION`` env var).

    Returns:
        The retrieved ``modelarmor_v1.Template`` object.
    """
    from google.cloud import modelarmor_v1

    _project_id = project_id or GCP_PROJECT_ID
    _location = location or GCP_LOCATION

    request = modelarmor_v1.GetTemplateRequest(
        name=f"projects/{_project_id}/locations/{_location}/templates/{template_name}"
    )
    return client.get_template(request=request)


def sanitize_prompt(
    client: Any,
    prompt: str,
    project_id: str | None = None,
    location: str | None = None,
    template_id: str | None = None,
) -> Any:
    """Sanitize a text prompt using the Model Armor template.

    Args:
        client:      A ``modelarmor_v1.ModelArmorClient`` instance.
        prompt:      The text to sanitize.
        project_id:  GCP project (defaults to ``GCP_PROJECT_ID`` env var).
        location:    GCP region (defaults to ``GCP_LOCATION`` env var).
        template_id: Template identifier (defaults to ``MODEL_ARMOR_TEMPLATE_ID``).

    Returns:
        A raw ``SanitizeUserPromptResponse`` protobuf object.
    """
    from google.cloud import modelarmor_v1

    _project_id = project_id or GCP_PROJECT_ID
    _location = location or GCP_LOCATION
    _template_id = template_id or MODEL_ARMOR_TEMPLATE_ID

    user_prompt_data = modelarmor_v1.DataItem(text=prompt)
    request = modelarmor_v1.SanitizeUserPromptRequest(
        name=f"projects/{_project_id}/locations/{_location}/templates/{_template_id}",
        user_prompt_data=user_prompt_data,
    )
    return client.sanitize_user_prompt(request=request)


# ---------------------------------------------------------------------------
# SDK-like client classes (consumed by app.core.guardrails providers)
# ---------------------------------------------------------------------------


class ModelArmorClient:
    """Synchronous Model Armor client with a guardrails-compatible interface.

    Usage::

        client = ModelArmorClient(project_id, location, template_id)
        result = client.check_prompt("user input")
        if result.is_blocked:
            ...
    """

    def __init__(self, project_id: str, location: str, template_id: str) -> None:
        self.project_id = project_id
        self.location = location
        self.template_id = template_id
        self._api_client: Any = None

    @property
    def _client(self) -> Any:
        """Lazily initialise the underlying API client."""
        if self._api_client is None:
            self._api_client = _build_api_client(self.location)
        return self._api_client

    def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> ModelArmorResult:
        """Check a single prompt and return a normalised result."""
        response = sanitize_prompt(
            self._client,
            content,
            project_id=self.project_id,
            location=self.location,
            template_id=self.template_id,
        )
        return _map_sanitize_response(response)

    def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> ModelArmorResult:
        """Check the most recent user turn in a conversation."""
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        content = user_messages[-1] if user_messages else ""
        return self.check_prompt(content, user_id=user_id)


class AsyncModelArmorClient:
    """Async Model Armor client wrapping ``ModelArmorClient`` via ``asyncio.to_thread``.

    The underlying Google Cloud SDK is synchronous; this class offloads each
    call to a thread pool so it can be used in async FastAPI routes without
    blocking the event loop.

    Usage::

        client = AsyncModelArmorClient(project_id, location, template_id)
        result = await client.check_prompt("user input")
        if result.is_blocked:
            ...
        await client.close()  # no-op, provided for interface compatibility
    """

    def __init__(self, project_id: str, location: str, template_id: str) -> None:
        self._sync = ModelArmorClient(project_id, location, template_id)

    async def check_prompt(
        self, content: str, user_id: str | None = None
    ) -> ModelArmorResult:
        return await asyncio.to_thread(self._sync.check_prompt, content, user_id)

    async def check_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
    ) -> ModelArmorResult:
        return await asyncio.to_thread(self._sync.check_conversation, messages, user_id)

    async def close(self) -> None:
        """No-op; provided for interface compatibility with async providers."""
        pass


# ---------------------------------------------------------------------------
# Script entry-point (quick smoke-test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Validate required environment variables before running
    for _var in ("GCP_PROJECT_ID", "GCP_LOCATION", "MODEL_ARMOR_TEMPLATE_ID"):
        if not os.getenv(_var):
            raise ValueError(f"{_var} environment variable is required. Check your .env file.")

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    client = init()

    try:
        start_time = time.time()
        delete_template(client, MODEL_ARMOR_TEMPLATE_ID)
        logging.info("Existing Model Armor template deleted successfully (if it existed).")
        create_template(client)
        logging.info("Model Armor template created successfully.")
        sanitized_prompt = sanitize_prompt(client, "How are you doing today?")
        end_time = time.time()

        latency_ms = (end_time - start_time) * 1000
        logging.info(f"Model Armor sanitize_prompt latency: {latency_ms:.2f}ms")
        print(f"✅ Prompt sanitized successfully: {sanitized_prompt}")
        print(f"⏱️  Latency: {latency_ms:.2f}ms")
    except Exception as e:
        print(f"❌ Failed: {e}")
