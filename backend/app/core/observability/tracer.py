from __future__ import annotations

from app.core.logger import app_logger

_initialised = False


def setup_langtrace() -> None:
    """
    Initialise Langtrace and wire up the SQLite span exporter.

    Reads configuration from app.core.env:
        LANGTRACE_API_KEY   – optional; omit for local-only mode (no cloud upload)
        LANGTRACE_CONSOLE   – bool; print spans to stdout when True

    Safe to call multiple times (subsequent calls are no-ops).
    """
    global _initialised
    if _initialised:
        app_logger.debug("setup_langtrace() called more than once — skipping.")
        return

    # Late imports so this module can be imported without side-effects
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
    from langtrace_python_sdk import langtrace  # noqa: F401

    from app.core.env import env
    from app.core.observability.exporter import SQLiteSpanExporter

    # ── Build TracerProvider ───────────────────────────────────────────────
    provider = TracerProvider()
    sqlite_exporter = SQLiteSpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(sqlite_exporter))

    if env.LANGTRACE_CONSOLE or env.ENVIRONMENT == "development":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        app_logger.debug("Langtrace: console span export enabled.")

    # ── Initialise Langtrace SDK ───────────────────────────────────────────
    # custom_remote_exporter injects our SQLiteSpanExporter instead of (or
    # alongside) the Langtrace cloud backend.
    init_kwargs: dict = dict(
        custom_remote_exporter=sqlite_exporter,
    )

    if env.LANGTRACE_API_KEY:
        init_kwargs["api_key"] = env.LANGTRACE_API_KEY
        app_logger.info("Langtrace: cloud upload enabled (LANGTRACE_API_KEY set).")
    else:
        app_logger.info(
            "Langtrace: LANGTRACE_API_KEY not set — storing traces locally only."
        )

    langtrace.init(**init_kwargs)

    _initialised = True
    app_logger.success("Langtrace initialised — Vertex AI instrumentation active.")