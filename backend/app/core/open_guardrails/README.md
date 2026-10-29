# OpenGuardrails — Plug-and-Play Guardrails Backend

[OpenGuardrails](https://openguardrails.com) provides prompt injection detection, content compliance, and sensitive-data-leak prevention for LLM applications. This module integrates it as a **plug-and-play guardrails backend** alongside the Google Cloud Model Armor option.

---

## Quick Start

### 1. Copy `.env.sample` values into the root `.env`

```bash
# .env (root backend .env)
GUARDRAILS_BACKEND=openguardrails
OPENGUARDRAILS_API_KEY=your-api-key-here
```

### 2. Install the dependency

```bash
# Install only the open_guardrails group (other optional groups will be removed from the environment)
uv sync --group open_guardrails

# Install all optional groups (recommended for full dev setup)
uv sync --all-groups
```

### 3. Use in routes — no code changes needed

The guardrails backend is selected entirely from `.env`. All existing routes that use `async_guardrails()` or the `guardrails` singleton will transparently use OpenGuardrails:

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

### 4. Run the smoke-test script

```bash
uv run python -m app.core.open_guardrails.open_guardrails
```

---

## Architecture

```
app.core.guardrails (guardrails.py)
    ├── OpenGuardrailsProvider(BaseGuardrails)           ← sync, wraps OpenGuardrailsClient
    └── AsyncOpenGuardrailsProvider(BaseAsyncGuardrails) ← async, wraps AsyncOpenGuardrailsClient
              │
              ▼
app.core.open_guardrails.open_guardrails
    ├── OpenGuardrailsClient       ← sync; lazy-inits SDK client on first use
    └── AsyncOpenGuardrailsClient  ← async; uses native async SDK (not thread pool)
```

The backend selection in `guardrails.py` reads `env.guardrails_backend` at startup:

| `GUARDRAILS_BACKEND` value | Provider used |
|---|---|
| `openguardrails` | `OpenGuardrailsProvider` / `AsyncOpenGuardrailsProvider` |
| `model_armor` | `ModelArmorProvider` / `AsyncModelArmorProvider` |
| `none` (default) | `NoOpGuardrails` — always passes, zero external calls |

---

## Response Fields

Both sync (`check_prompt`, `check_conversation`) and async methods return a `GuardrailResponse` with:

| Field | Type | Description |
|---|---|---|
| `is_blocked` | `bool` | `True` when content failed a check |
| `is_safe` | `bool` | Inverse of `is_blocked` |
| `suggest_action` | `str` | `"block"` or `"pass"` |
| `overall_risk_level` | `str` | e.g. `"no_risk"`, `"medium"`, `"high"` |
| `score` | `float` | Safety score (provider-dependent) |
| `raw_response` | `Any` | Unmodified SDK response object |

---

## Configuration

Connection settings are stored in [`filter_config.yaml`](filter_config.yaml) — safe to commit, no secrets.

| Setting | Default | Description |
|---|---|---|
| `client.base_url` | `https://api.openguardrails.com/v1` | OpenGuardrails API endpoint |
| `client.timeout` | `30` | Request timeout in seconds |
| `client.max_retries` | `3` | Number of retries on transient failures |

---

## Environment Variables

| Variable | Required | Description | Example |
|---|---|---|---|
| `GUARDRAILS_BACKEND` | ✅ | Must be `openguardrails` | `openguardrails` |
| `OPENGUARDRAILS_API_KEY` | ✅ | Your OpenGuardrails API key | `sk-xxai-...` |

See [`.env.sample`](.env.sample) for a ready-to-copy template.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `ImportError: openguardrails package not found` | Package missing | `uv sync --extra guardrails` |
| `401 Unauthorized` | Invalid API key | Check `OPENGUARDRAILS_API_KEY` in `.env` |
| `ValueError: OPENGUARDRAILS_API_KEY is required` | Missing env var | Set the key in `.env` |

---

## License

This module follows the same license as the parent repository.
