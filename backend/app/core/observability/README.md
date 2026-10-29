# Observability Module

End-to-end observability for LLM calls, combining **Langtrace**, **OpenTelemetry**, and a custom SQLite exporter.

---

## What it does

- Automatically traces LLM calls via Langtrace
- Persists spans and audit data to SQLite (same DB as the app)
- Logs blocked prompts/responses from the configured guardrail backend
- Computes daily per-model metrics for dashboards and reporting
- Optionally uploads traces to the Langtrace cloud dashboard

---

## Architecture

```
LLM call (e.g. Vertex AI / Gemini)
        │
        ▼
Langtrace instrumentation
        │
OpenTelemetry spans
        │
        ├── ConsoleSpanExporter     (dev/debug)
        └── SQLiteSpanExporter      (persistent storage)
                │
                ▼
        SQLite
          ├── langtrace_spans
          ├── langtrace_metric_summaries
          └── langtrace_blocked_events
```

---

## Module structure

```
app/core/observability/
├── __init__.py     # Public API
├── tracer.py       # Langtrace + OTEL setup
├── exporter.py     # Custom SQLite span exporter
├── models.py       # SQLModel table definitions
└── metrics.py      # Query helpers, aggregations, blocked event logging
```

---

## Setup

### 1. Install dependencies

```bash
# Install only the observability group (other optional groups will be removed from the environment)
uv sync --group observability

# Install all optional groups (recommended for full dev setup)
uv sync --all-groups
```

### 2. Environment variables

```env
LANGTRACE_API_KEY=your_key        # Optional — omit for local-only mode
LANGTRACE_CONSOLE=true            # Print spans to stdout (dev only)
ENVIRONMENT=development
GUARDRAILS_BACKEND=model_armor # Guardrail provider for input/output checks: model_armor | none
```

### 3. Initialise at startup

Add to `app/main.py` before any other imports:

```python
from app.core.observability import setup_langtrace
setup_langtrace()
```

### 4. Register DB tables

Add to `app/core/db.py` inside `init_db()`:

```python
from app.core.observability import models as _obs_models  # noqa: F401
```

---

## Database tables

### `langtrace_spans`
One row per LLM call, auto-populated by Langtrace. Audit fields are written back after the call completes.

| Field | Description |
|---|---|
| `trace_id`, `span_id` | OTEL trace identifiers |
| `parent_span_id` | Parent span for nested traces |
| `span_name` | e.g. `vertexai.generate_content` |
| `service_name` | Service that made the call |
| `model` | e.g. `gemini-2.5-flash` |
| `start_time`, `end_time` | Call timing |
| `duration_ms` | End-to-end latency |
| `input_tokens`, `output_tokens`, `total_tokens` | Token usage |
| `status_code` | `OK` or `ERROR` |
| `error_message` | Error detail when `status_code = ERROR` |
| `prompt_text` | Raw input prompt (audit) |
| `response_text` | Model output (audit) |
| `user_id` | Identity of the requester |
| `session_id` | Groups spans across a conversation |
| `attributes_json` | Full raw OTEL attributes (debug/audit) |
| `guardrail_backend` | Active provider: `model_armor` or `null` if none |
| `guardrail_input_checked` | `true` when input was sent through guardrails |
| `guardrail_input_is_safe` | Input guardrail verdict (`null` = not checked) |
| `guardrail_input_risk_level` | Input risk level string |
| `guardrail_input_score` | Raw input safety score |
| `guardrail_output_checked` | `true` when output was sent through guardrails |
| `guardrail_output_is_safe` | Output guardrail verdict (`null` = not checked) |
| `guardrail_output_risk_level` | Output risk level string |
| `guardrail_output_score` | Raw output safety score |

---

### `langtrace_blocked_events`
One row per blocked prompt or response, from any safety layer.

| Field | Description |
|---|---|
| `blocked_by` | `model_armor` \| `guardrails_input` \| `guardrails_output` |
| `blocked_text` | The prompt or response that was blocked |
| `risk_level` | Filter(s) that triggered e.g. `HATE_SPEECH(HIGH), PI_JAILBREAK(HIGH)` |
| `score` | Raw safety score |
| `is_safe` | Boolean safety result |
| `user_id` | Who triggered the block |
| `model` | Model in use at the time |
| `session_id` | Session the block occurred in |
| `raw_detail` | Full raw guardrail response (for debugging) |

---

### `langtrace_metric_summaries`
Aggregated daily metrics per model. Populated by calling `persist_daily_summary()`.

| Field | Description |
|---|---|
| `date` | `YYYY-MM-DD` |
| `model` | Model name |
| `total_requests` | Total span count |
| `successful_requests` | `status_code = OK` count |
| `failed_requests` | `status_code = ERROR` count |
| `total_input_tokens` | Sum of input tokens |
| `total_output_tokens` | Sum of output tokens |
| `avg_latency_ms` | Average latency |
| `p95_latency_ms` | 95th percentile latency |
| `max_latency_ms` | Max latency |
| `guardrail_blocks` | Total guardrail blocks (input + output combined) |
| `guardrail_input_blocks` | Input-only guardrail blocks |
| `guardrail_output_blocks` | Output-only guardrail blocks |

Block counts are backend-agnostic — they count events from any guardrail provider. To see which backend caused a specific block, query `langtrace_blocked_events.blocked_by` or `langtrace_spans.guardrail_backend`.

---

## Safety pipeline

The `POST /observability/chat/with-guardrails-observability` endpoint runs this pipeline:

```
User prompt
    │
    ▼
1. Guardrails on INPUT     → checks prompt safety (backend: model_armor)
    │                         blocked_by = "guardrails_input"
    ▼
2. LLM call                → generates response (auto-traced by Langtrace/OTEL)
    │
    ▼
3. Guardrails on OUTPUT    → checks response safety (backend: model_armor)
    │                         blocked_by = "guardrails_output"
    ▼
4. Span enrichment         → writes audit fields back to langtrace_spans
```

The guardrail backend is selected via the `guardrails_backend` env var (`model_armor` | `none`). Any block at steps 1 or 3 writes a row to `langtrace_blocked_events` before returning.

---

## Query helpers

```python
from app.core.observability import (
    get_recent_spans,        # Latest spans, filterable by model/status
    get_spans_by_trace,      # All spans for a single trace_id
    compute_daily_summary,   # In-memory aggregation for a given date
    persist_daily_summary,   # Upsert daily summary to DB (use in cron)
    get_summary_range,       # Historical summaries for last N days
)
from app.core.observability.metrics import log_blocked_event  # Log a block manually
```

---

## API endpoints

All observability endpoints are mounted under the `observability` tag.

| Method | Path | Description |
|---|---|---|
| `POST` | `/observability/chat/with-guardrails-observability` | Chat with guardrails + full span enrichment |
| `GET` | `/observability/blocked-events` | List blocked events, filterable by `user_id` |
| `POST` | `/observability/computedailysummary` | Compute and persist daily metrics |

---

## Inspecting the database

```bash
# View recent spans
python -c "
from app.core.db import engine
from sqlmodel import Session, select
from app.core.observability.models import LangtraceSpan
with Session(engine) as s:
    for span in s.exec(select(LangtraceSpan).limit(10)).all():
        print(span.span_name, span.model, span.status_code, span.duration_ms)
"

# View blocked events
python -c "
from app.core.db import engine
from sqlmodel import Session, select
from app.core.observability.models import LangtraceBlockedEvent
with Session(engine) as s:
    for e in s.exec(select(LangtraceBlockedEvent)).all():
        print(e.blocked_by, e.risk_level, e.user_id, e.blocked_text[:60])
"
```

Or open `database.db` directly with [DB Browser for SQLite](https://sqlitebrowser.org) or the VS Code **SQLite Viewer** extension.

---

## Design principles

- **Local-first** — works without cloud connectivity
- **Backend-agnostic** — guardrail fields and metrics work with Model Armor or no provider
- **Audit-friendly** — prompt, response, and safety decisions are all stored
- **Safe-by-default** — no side effects until `setup_langtrace()` is called
- **Composable** — metrics can power APIs, dashboards, or alerts
