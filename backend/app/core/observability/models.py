from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class LangtraceSpan(SQLModel, table=True):
    """One OTEL span emitted by Langtrace for a Vertex AI call."""

    __tablename__ = "langtrace_spans"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Trace / span identifiers
    trace_id: str = Field(index=True)
    span_id: str = Field(index=True)
    parent_span_id: Optional[str] = Field(default=None)

    # Operation metadata
    span_name: str  # e.g. "vertexai.generate_content"
    service_name: str = Field(default="vertex-ai")  # e.g. "vertex-ai"
    model: Optional[str] = Field(default=None)  # e.g. "gemini-1.5-flash"

    # Timing
    start_time: datetime
    end_time: Optional[datetime] = Field(default=None)
    duration_ms: Optional[float] = Field(default=None)

    # Token usage (OpenTelemetry Gen AI semantic conventions)
    input_tokens: Optional[int] = Field(default=None)
    output_tokens: Optional[int] = Field(default=None)
    total_tokens: Optional[int] = Field(default=None)

    # Status
    status_code: str = Field(default="OK")  # "OK" | "ERROR"
    error_message: Optional[str] = Field(default=None)

    # Safety layer context (generic — works with any guardrail backend or none)
    # Which guardrail backend was active for this call, if any.
    guardrail_backend: Optional[str] = Field(default=None)

    # Input guardrail — None fields mean the check was not performed
    guardrail_input_checked: bool = Field(
        default=False
    )  # True when input was sent through guardrails
    guardrail_input_is_safe: Optional[bool] = Field(default=None)
    guardrail_input_risk_level: Optional[str] = Field(default=None)
    guardrail_input_score: Optional[float] = Field(default=None)

    # Output guardrail — None fields mean the check was not performed
    guardrail_output_checked: bool = Field(
        default=False
    )  # True when output was sent through guardrails
    guardrail_output_is_safe: Optional[bool] = Field(default=None)
    guardrail_output_risk_level: Optional[str] = Field(default=None)
    guardrail_output_score: Optional[float] = Field(default=None)

    # Full OTEL attributes as JSON (for debugging/auditing)
    attributes_json: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Audit fields
    prompt_text: Optional[str] = Field(default=None)
    response_text: Optional[str] = Field(default=None)

    # User / session identity
    user_id: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(
        default=None
    )  # Groups spans across a conversation


class LangtraceMetricSummary(SQLModel, table=True):
    """Aggregated per-model daily metrics — suitable for dashboards."""

    __tablename__ = "langtrace_metric_summaries"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)  # "YYYY-MM-DD"
    model: str = Field(index=True)

    total_requests: int = Field(default=0)
    successful_requests: int = Field(default=0)
    failed_requests: int = Field(default=0)

    total_input_tokens: int = Field(default=0)
    total_output_tokens: int = Field(default=0)

    avg_latency_ms: float = Field(default=0.0)
    p95_latency_ms: float = Field(default=0.0)
    max_latency_ms: float = Field(default=0.0)

    # Safety layer hit counts (backend-agnostic)
    guardrail_blocks: int = Field(default=0)  # total input + output blocks
    guardrail_input_blocks: int = Field(default=0)  # blocks on the input/prompt
    guardrail_output_blocks: int = Field(default=0)  # blocks on the output/response

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LangtraceBlockedEvent(SQLModel, table=True):
    __tablename__ = "langtrace_blocked_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(default="anonymous", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    blocked_by: str
    blocked_text: str
    risk_level: Optional[str] = Field(default=None)
    score: Optional[float] = Field(default=None)
    is_safe: Optional[bool] = Field(default=None)
    model: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(default=None)
    raw_detail: Optional[str] = Field(default=None)
