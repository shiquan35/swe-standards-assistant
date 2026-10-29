from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode
from sqlmodel import Session

from app.core.logger import app_logger

# Nanosecond conversion helpers
_NS_TO_MS = 1e-6
_NS_TO_S = 1e-9


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns * _NS_TO_S, tz=timezone.utc).replace(tzinfo=None)


class SQLiteSpanExporter(SpanExporter):
    """
    Exports OTEL spans produced by Langtrace into the app's SQLite database.

    Reuses the engine from app.core.db so there is a single connection pool
    and a single DB file for the whole application.
    """

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        # Late import to avoid circular dependency at module load time
        from app.core.db import engine
        from app.core.observability.models import LangtraceSpan

        records: list[LangtraceSpan] = []

        for span in spans:
            try:
                attrs = dict(span.attributes or {})

                # ── Timing ────────────────────────────────────────────────
                start_dt = _ns_to_dt(span.start_time) if span.start_time else datetime.utcnow()
                end_dt = _ns_to_dt(span.end_time) if span.end_time else None
                duration = (
                    (span.end_time - span.start_time) * _NS_TO_MS
                    if span.end_time and span.start_time
                    else None
                )

                # ── Status ────────────────────────────────────────────────
                is_error = span.status.status_code == StatusCode.ERROR
                status_str = "ERROR" if is_error else "OK"
                error_msg = span.status.description if is_error else None

                # ── Token usage (OTEL Gen AI semantic conventions) ─────────
                input_tokens = (
                    attrs.get("gen_ai.usage.input_tokens")
                    or attrs.get("gen_ai.usage.prompt_tokens")
                )
                output_tokens = (
                    attrs.get("gen_ai.usage.output_tokens")
                    or attrs.get("gen_ai.usage.completion_tokens")
                )
                total_tokens = (
                    int(input_tokens) + int(output_tokens)
                    if input_tokens is not None and output_tokens is not None
                    else None
                )

                # ── Model name ─────────────────────────────────────────────
                model = (
                    attrs.get("gen_ai.response.model")
                    or attrs.get("gen_ai.request.model")
                    or attrs.get("llm.model")
                )

                records.append(
                    LangtraceSpan(
                        trace_id=format(span.context.trace_id, "032x"),
                        span_id=format(span.context.span_id, "016x"),
                        parent_span_id=(
                            format(span.parent.span_id, "016x") if span.parent else None
                        ),
                        span_name=span.name,
                        service_name=attrs.get("service.name", "vertex-ai"),
                        model=model,
                        start_time=start_dt,
                        end_time=end_dt,
                        duration_ms=round(duration, 3) if duration is not None else None,
                        input_tokens=int(input_tokens) if input_tokens is not None else None,
                        output_tokens=int(output_tokens) if output_tokens is not None else None,
                        total_tokens=total_tokens,
                        status_code=status_str,
                        error_message=error_msg,
                        attributes_json=json.dumps(attrs),
                    )
                )
            except Exception as exc:
                app_logger.warning(
                    "SQLiteSpanExporter: failed to parse span '{}' — {}", span.name, exc
                )

        if not records:
            return SpanExportResult.SUCCESS

        try:
            with Session(engine) as session:
                session.add_all(records)
                session.commit()
            # after committing to the database, we should then convert results into a JSON file in order to store.
            app_logger.debug(
                "SQLiteSpanExporter: saved {} span(s)", len(records)
            )
        except Exception as exc:
            app_logger.error("SQLiteSpanExporter: DB write failed — {}", exc)
            return SpanExportResult.FAILURE

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass
