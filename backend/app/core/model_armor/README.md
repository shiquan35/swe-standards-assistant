# Model Armor — Google Cloud RAI Guardrails

Google Cloud [Model Armor](https://cloud.google.com/model-armor/docs) provides Responsible AI (RAI) content filtering for LLM prompts and responses. This module integrates Model Armor as a **plug-and-play guardrails backend** for the application, alongside the existing OpenGuardrails option.

---

## Quick Start

### 1. Copy `.env.sample` values into the root `.env`

```bash
# .env (root backend .env)
GUARDRAILS_BACKEND=model_armor

GCP_PROJECT_ID=your-gcp-project-id
GCP_LOCATION=us-central1
MODEL_ARMOR_TEMPLATE_ID=your-template-id
```

### 2. Install the dependency

```bash
# Install only the model_armor group (other optional groups will be removed from the environment)
uv sync --group model_armor

# Install all optional groups (recommended for full dev setup)
uv sync --all-groups
```

### 3. Create the filtering template (one-time setup)

```python
from app.core.model_armor.model_armor import init, create_template

client = init()
template_name = create_template(client)
print(f"Template created: {template_name}")
```

Or run the smoke-test script directly:

```bash
uv run python -m app.core.model_armor.model_armor
```

### 4. Use in routes — no code changes needed

The guardrails backend is selected entirely from `.env`. All existing routes that use `async_guardrails()` or the `guardrails` singleton will transparently use Model Armor:

```python
from app.core.guardrails import async_guardrails

@router.post("/chat")
async def chat(request: ChatRequest):
    async with async_guardrails() as client:
        result = await client.check_prompt(request.prompt, user_id=request.user_id)
        if result.is_blocked:
            raise HTTPException(status_code=400, detail="Content blocked by guardrails")
    # ... call LLM ...
```

---

## Architecture

```
app.core.guardrails (guardrails.py)
    ├── ModelArmorProvider(BaseGuardrails)           ← sync, wraps ModelArmorClient
    └── AsyncModelArmorProvider(BaseAsyncGuardrails) ← async, wraps AsyncModelArmorClient
              │
              ▼
app.core.model_armor.model_armor
    ├── ModelArmorClient        ← sync; lazy-inits GCP API client on first use
    ├── AsyncModelArmorClient   ← async wrapper via asyncio.to_thread
    └── low-level helpers       ← init(), create_template(), sanitize_prompt(), …
```

The backend selection in `guardrails.py` reads `env.guardrails_backend` at startup:

| `GUARDRAILS_BACKEND` value | Provider used |
|---|---|
| `model_armor` | `ModelArmorProvider` / `AsyncModelArmorProvider` |
| `openguardrails` | `OpenGuardrailsProvider` / `AsyncOpenGuardrailsProvider` |
| `none` (default) | `NoOpGuardrails` — always passes, zero external calls |

---

## Response Fields

Both sync (`check_prompt`, `check_conversation`) and async methods return a `GuardrailResponse` with:

| Field | Type | Description |
|---|---|---|
| `is_blocked` | `bool` | `True` when a filter matched |
| `is_safe` | `bool` | Inverse of `is_blocked` |
| `suggest_action` | `str` | `"block"` or `"pass"` |
| `overall_risk_level` | `str` | `"high"` (blocked) or `"no_risk"` (safe) |
| `raw_response` | `Any` | Raw `SanitizeUserPromptResponse` protobuf |

---

## Filter Configuration

Filters are defined in [`filter_config.yaml`](filter_config.yaml) — safe to commit, no secrets.

### Default RAI filters

| Filter | Confidence level |
|---|---|
| Hate Speech | `MEDIUM_AND_ABOVE` |
| Dangerous Content | `MEDIUM_AND_ABOVE` |
| Sexually Explicit | `MEDIUM_AND_ABOVE` |
| Harassment | `MEDIUM_AND_ABOVE` |

### PI / Jailbreak protection

| Setting | Value |
|---|---|
| Filter Enforcement | `ENABLED` |
| Confidence Level | `MEDIUM_AND_ABOVE` |

To change sensitivity, edit `filter_config.yaml` and recreate the template.

---

## Environment Variables

| Variable | Required | Description | Example |
|---|---|---|---|
| `GUARDRAILS_BACKEND` | ✅ | Must be `model_armor` | `model_armor` |
| `GCP_PROJECT_ID` | ✅ | Google Cloud project ID | `my-project-123` |
| `GCP_LOCATION` | ✅ | GCP region for Model Armor | `us-central1` |
| `MODEL_ARMOR_TEMPLATE_ID` | ✅ | Template identifier | `my-template-v1` |
| `GOOGLE_APPLICATION_CREDENTIALS` | ❌ | Service account key path (optional) | `/path/to/key.json` |

See [`.env.sample`](.env.sample) for a ready-to-copy template.

---

## Prerequisites

### Google Cloud Setup

1. **Enable the API**
   ```bash
   gcloud services enable modelarmor.googleapis.com
   ```

2. **Authenticate**
   ```bash
   gcloud auth application-default login
   ```

3. **Grant IAM permissions** — `Model Armor Admin` or `Model Armor User` role on the project.

### Supported Regions

| Region | Location |
|---|---|
| `us-central1` | Iowa |
| `us-east1` | South Carolina |
| `us-west1` | Oregon |
| `europe-west1` | Belgium |
| `asia-southeast1` | Singapore |

See the [official docs](https://cloud.google.com/model-armor/docs/locations) for the full list.

---

## Low-level Helper Functions

Use these for template lifecycle scripts, not in application routes.

```python
from app.core.model_armor.model_armor import (
    init, create_template, delete_template, get_template, sanitize_prompt
)

client = init()

# Template lifecycle
template_name = create_template(client)
template      = get_template(client, "my-template-id")
delete_template(client, "my-template-id")

# Direct sanitization — returns raw SanitizeUserPromptResponse
raw = sanitize_prompt(client, "How do I make a bomb?")
```

All helpers accept optional `project_id`, `location`, and `template_id` keyword arguments that override the corresponding environment variables.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `ImportError: google-cloud-modelarmor not installed` | Package missing | `uv add google-cloud-modelarmor` |
| `DefaultCredentialsError` | No GCP credentials | `gcloud auth application-default login` |
| `NotFound: Template not found` | Template not created | Run `create_template(client)` first |
| `ValueError: GCP_LOCATION must be provided` | Missing env var | Set `GCP_LOCATION` in `.env` |

Enable debug logging for more detail:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## License

This module follows the same license as the parent repository.
