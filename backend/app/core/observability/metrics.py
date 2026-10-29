from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, col, func, select

from app.core.logger import app_logger


def get_recent_spans(
    limit: int = 50,
    model: Optional[str] = None,
    status: Optional[str] = None,
    session: Optional[Session] = None,
) -> list:
    """Return the most recent LangtraceSpan rows, newest first."""
    from app.core.db import engine
    from app.core.observability.models import LangtraceSpan

    _session = session or Session(engine)
    _owns = session is None
    try:
        stmt = select(LangtraceSpan).order_by(col(LangtraceSpan.created_at).desc())
        if model:
            stmt = stmt.where(LangtraceSpan.model == model)
        if status:
            stmt = stmt.where(LangtraceSpan.status_code == status)
        return list(_session.exec(stmt.limit(limit)).all())
    finally:
        if _owns:
            _session.close()


def get_spans_by_trace(trace_id: str, session: Optional[Session] = None) -> list:
    """Return all spans belonging to a single trace."""
    from app.core.db import engine
    from app.core.observability.models import LangtraceSpan

    _session = session or Session(engine)
    _owns = session is None
    try:
        stmt = select(LangtraceSpan).where(LangtraceSpan.trace_id == trace_id)
        return list(_session.exec(stmt).all())
    finally:
        if _owns:
            _session.close()


def compute_daily_summary(
    date: Optional[datetime] = None,
    session: Optional[Session] = None,
) -> list[dict]:
    """
    Compute per-model summary stats for one calendar day (defaults to today UTC).

    Returns a list of dicts (one per model) — suitable for
    persist_daily_summary() or direct API responses.
    """
    from app.core.db import engine
    from app.core.observability.models import LangtraceSpan

    _session = session or Session(engine)
    _owns = session is None
    target_date = (date or datetime.utcnow()).strftime("%Y-%m-%d")

    try:
        stmt = select(LangtraceSpan).where(
            func.strftime("%Y-%m-%d", LangtraceSpan.start_time) == target_date,
            LangtraceSpan.model != None,
        )
        spans = list(_session.exec(stmt).all())
    finally:
        if _owns:
            _session.close()

    # Group by model
    by_model: dict[str, list] = {}
    for span in spans:
        by_model.setdefault(span.model or "unknown", []).append(span)

    summaries: list[dict] = []
    for model, model_spans in by_model.items():
        latencies = sorted(s.duration_ms for s in model_spans if s.duration_ms is not None)
        n = len(latencies)
        summaries.append(
            {
                "date": target_date,
                "model": model,
                "total_requests": len(model_spans),
                "successful_requests": sum(1 for s in model_spans if s.status_code == "OK"),
                "failed_requests": sum(1 for s in model_spans if s.status_code == "ERROR"),
                "total_input_tokens": sum(s.input_tokens or 0 for s in model_spans),
                "total_output_tokens": sum(s.output_tokens or 0 for s in model_spans),
                "avg_latency_ms": round(sum(latencies) / n, 2) if n else 0.0,
                "p95_latency_ms": round(latencies[max(0, int(n * 0.95) - 1)], 2) if n else 0.0,
                "max_latency_ms": round(latencies[-1], 2) if n else 0.0,
                "guardrail_blocks": sum(
                    1 for s in model_spans
                    if s.guardrail_input_is_safe is False or s.guardrail_output_is_safe is False
                ),
            }
        )

    return summaries


def extract_armor_block_reasons(sanitize_result) -> str:
    """Extract which Model Armor filters triggered and at what confidence."""
    triggered = []

    if not sanitize_result:
        return "unknown"

    try:
        filter_results = sanitize_result.filter_results

        # ── RAI filters ───────────────────────────────────────────────
        rai = filter_results.get("rai")
        if rai and str(rai.rai_filter_result.match_state) == "MATCH_FOUND":
            for filter_name, result in rai.rai_filter_result.rai_filter_type_results.items():
                if str(result.match_state) == "MATCH_FOUND":
                    confidence = str(result.confidence_level)
                    triggered.append(f"{filter_name.upper()}({confidence})")

        # ── PI / Jailbreak ────────────────────────────────────────────
        pi = filter_results.get("pi_and_jailbreak")
        if pi and str(pi.pi_and_jailbreak_filter_result.match_state) == "MATCH_FOUND":
            confidence = str(pi.pi_and_jailbreak_filter_result.confidence_level)
            triggered.append(f"PI_JAILBREAK({confidence})")

        # ── CSAM ──────────────────────────────────────────────────────
        csam = filter_results.get("csam")
        if csam and str(csam.csam_filter_filter_result.match_state) == "MATCH_FOUND":
            triggered.append("CSAM")

    except Exception as exc:
        from app.core.logger import app_logger
        app_logger.warning("Could not extract armor block reasons: {}", exc)
        return "unknown"

    return ", ".join(triggered) if triggered else "unknown"

def log_blocked_event(
    blocked_by: str,
    blocked_text: str,
    user_id: str = "anonymous",
    risk_level: Optional[str] = None,
    score: Optional[float] = None,
    is_safe: Optional[bool] = None,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    raw_detail: Optional[str] = None, 
) -> None:
    from app.core.db import engine
    from app.core.observability.models import LangtraceBlockedEvent

    try:
        record = LangtraceBlockedEvent(
            user_id=user_id,
            blocked_by=blocked_by,
            blocked_text=blocked_text,
            risk_level=risk_level,
            score=score,
            is_safe=is_safe,
            model=model,
            session_id=session_id,
            raw_detail=raw_detail,
        )
        with Session(engine) as session:
            session.add(record)
            session.commit()
        app_logger.info(
            "Blocked event logged: blocked_by={} user={} reason={}", 
            blocked_by, user_id, risk_level
        )
    except Exception as exc:
        app_logger.error("Failed to log blocked event: {}", exc)


def persist_daily_summary(
    date: Optional[datetime] = None,
    session: Optional[Session] = None,
) -> list:
    from app.core.db import engine
    from app.core.observability.models import LangtraceMetricSummary, LangtraceBlockedEvent

    rows = compute_daily_summary(date, session)
    if not rows:
        return []

    _session = session or Session(engine)
    _owns = session is None
    target_date = (date or datetime.utcnow()).strftime("%Y-%m-%d")

    try:
        blocked_events = _session.exec(
            select(LangtraceBlockedEvent).where(
                func.strftime("%Y-%m-%d", LangtraceBlockedEvent.created_at) == target_date
            )
        ).all()

        guardrail_input_blocks = sum(1 for e in blocked_events if e.blocked_by == "guardrails_input")
        guardrail_output_blocks = sum(1 for e in blocked_events if e.blocked_by == "guardrails_output")
        guardrail_blocks = guardrail_input_blocks + guardrail_output_blocks

        saved = []
        for row in rows:
            row["guardrail_blocks"] = guardrail_blocks
            row["guardrail_input_blocks"] = guardrail_input_blocks
            row["guardrail_output_blocks"] = guardrail_output_blocks

            existing = _session.exec(
                select(LangtraceMetricSummary).where(
                    LangtraceMetricSummary.date == row["date"],
                    LangtraceMetricSummary.model == row["model"],
                )
            ).first()

            if existing:
                for k, v in row.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
                existing.updated_at = datetime.utcnow()
                _session.add(existing)
            else:
                _session.add(LangtraceMetricSummary(**row))

            saved.append(row)

        _session.commit()
        app_logger.info(
            "persist_daily_summary: {} row(s) | guardrail_input={} guardrail_output={} total={}",
            len(saved), guardrail_input_blocks, guardrail_output_blocks, guardrail_blocks
        )
        return saved

    finally:
        if _owns:
            _session.close()


def get_summary_range(days: int = 7, session: Optional[Session] = None) -> list:
    """Return persisted daily summaries for the last N days, newest first."""
    from app.core.db import engine
    from app.core.observability.models import LangtraceMetricSummary

    _session = session or Session(engine)
    _owns = session is None
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        stmt = (
            select(LangtraceMetricSummary)
            .where(LangtraceMetricSummary.date >= cutoff)
            .order_by(col(LangtraceMetricSummary.date).desc())
        )
        return list(_session.exec(stmt).all())
    finally:
        if _owns:
            _session.close()
