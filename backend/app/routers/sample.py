"""API router exposing Sample CRUD endpoints.

Prefixed with /samples so it's clearly an example set of endpoints.
Includes guardrails integration examples for LLM API calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi_pagination import Page
from pydantic import BaseModel

from sqlmodel import Session, col, select

from app.core.db import SessionDep, engine
from app.core.env import env
from app.core.guardrails import async_guardrails
from app.core.logger import app_logger
from app.core.observability.metrics import log_blocked_event, persist_daily_summary
from app.core.observability.models import LangtraceBlockedEvent, LangtraceSpan
from app.models.sample import SampleCreate, SampleRead, SampleUpdate
from app.services.sample import SampleService

router = APIRouter(prefix="/samples", tags=["sample"])
observability_router = APIRouter(tags=["observability"])


# ---------------------------------------------------------------------------
# Guardrails + LLM example models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Example request for LLM chat with guardrails."""

    prompt: str
    user_id: str | None = None
    model: str = "gpt-4"


class ChatResponse(BaseModel):
    """Example response from LLM with guardrails metadata."""

    response: str
    prompt_risk_level: str
    response_risk_level: str
    model_used: str


class DailySummaryRequest(BaseModel):
    """Request body for triggering daily metric aggregation."""

    date: str | None = None  # YYYY-MM-DD; defaults to today UTC when omitted


@router.get("/", response_model=Page[SampleRead])
def list_paginated(session: SessionDep):
    return SampleService.list(session)


@router.get("/{sample_id}", response_model=SampleRead)
def get_one(session: SessionDep, sample_id: str):
    return SampleService.get(session, sample_id=sample_id)


@router.post("/", response_model=SampleRead, status_code=status.HTTP_201_CREATED)
def create_one(session: SessionDep, data: SampleCreate):
    return SampleService.create(session, data=data)


@router.patch("/{sample_id}", response_model=SampleRead)
def update_one(
    session: SessionDep,
    sample_id: str,
    data: SampleUpdate,
):
    return SampleService.update(session, sample_id=sample_id, data=data)


@router.delete("/{sample_id}")
def delete_one(session: SessionDep, sample_id: str):
    SampleService.delete(session, sample_id=sample_id)
    return {"detail": f"ID: {sample_id} deleted"}


# ---------------------------------------------------------------------------
# Guardrails + LLM integration examples
# ---------------------------------------------------------------------------


@router.post("/chat/with-guardrails", response_model=ChatResponse)
async def chat_with_guardrails(request: ChatRequest):
    """Example: LLM chat with guardrails on both input and output.

    Pattern:
    1. Check user prompt with guardrails BEFORE sending to LLM
    2. If blocked, return error without calling LLM (save costs)
    3. Call LLM API
    4. Check LLM response with guardrails
    5. If response blocked, return sanitized error

    This is the recommended pattern for production LLM applications.
    """
    # Step 1: Check user input before sending to LLM
    async with async_guardrails() as client:
        prompt_check = await client.check_prompt(
            request.prompt, user_id=request.user_id
        )

        if prompt_check.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "prompt_blocked",
                    "message": "Your input violates content policies",
                    "risk_level": prompt_check.overall_risk_level,
                },
            )

    # Step 2: Call LLM API (example with OpenAI)
    # Uncomment and configure when ready:
    # from openai import AsyncOpenAI
    # openai_client = AsyncOpenAI(api_key=env.OPENAI_API_KEY)
    # completion = await openai_client.chat.completions.create(
    #     model=request.model,
    #     messages=[{"role": "user", "content": request.prompt}],
    # )
    # llm_response = completion.choices[0].message.content

    # For demo purposes, simulate LLM response
    llm_response = f"This is a simulated response to: {request.prompt}"

    # Step 3: Check LLM response before returning to user
    async with async_guardrails() as client:
        response_check = await client.check_prompt(llm_response)

        if response_check.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "response_blocked",
                    "message": "The generated response violates content policies",
                    "risk_level": response_check.overall_risk_level,
                },
            )

    return ChatResponse(
        response=llm_response,
        prompt_risk_level=prompt_check.overall_risk_level,
        response_risk_level=response_check.overall_risk_level,
        model_used=request.model,
    )


# ---------------------------------------------------------------------------
# Observability query endpoints
# ---------------------------------------------------------------------------


def _write_guardrails_span(
    *,
    request_start_time: datetime,
    model: str,
    user_id: str,
    prompt: str,
    llm_response: str | None,
    guardrail_backend: str | None,
    prompt_check,
    response_check=None,
    status_code: str = "OK",
) -> None:
    """Persist a LangtraceSpan record for a guardrails-observability request.

    Called on every exit path (success, input-blocked, output-blocked) so that
    langtrace_spans always has a full audit trail alongside langtrace_blocked_events.
    """
    try:
        now = datetime.utcnow()
        duration_ms = (now - request_start_time).total_seconds() * 1000

        span = LangtraceSpan(
            trace_id=uuid.uuid4().hex + uuid.uuid4().hex,
            span_id=uuid.uuid4().hex[:16],
            span_name="chat_with_guardrails_observability",
            service_name="aseanai-templates",
            model=model,
            start_time=request_start_time,
            end_time=now,
            duration_ms=round(duration_ms, 3),
            status_code=status_code,
            user_id=user_id,
            prompt_text=prompt,
            response_text=llm_response,
            guardrail_backend=guardrail_backend,
            guardrail_input_checked=True,
            guardrail_input_is_safe=prompt_check.is_safe,
            guardrail_input_risk_level=prompt_check.overall_risk_level,
            guardrail_input_score=prompt_check.score,
            guardrail_output_checked=response_check is not None,
            guardrail_output_is_safe=response_check.is_safe if response_check else None,
            guardrail_output_risk_level=response_check.overall_risk_level if response_check else None,
            guardrail_output_score=response_check.score if response_check else None,
        )

        with Session(engine) as session:
            session.add(span)
            session.commit()
    except Exception as exc:
        app_logger.warning("Could not write guardrails span: {}", exc)


@observability_router.post("/chat/with-guardrails-observability", response_model=ChatResponse)
async def chat_with_guardrails_observability(request: ChatRequest):
    """Chat with guardrails on input/output and full Langtrace/OpenTelemetry observability.

    Pattern:
    1. Check user prompt with guardrails — log blocked event and reject if unsafe
    2. Call LLM (auto-traced by Langtrace/OpenTelemetry)
    3. Check LLM response with guardrails — log blocked event and reject if unsafe
    4. Enrich the Langtrace span with audit data (prompt, response, guardrail results)
    """
    user_id = request.user_id or "anonymous"
    prompt = request.prompt
    request_start_time = datetime.utcnow()

    # ── Step 1: Guardrails on INPUT ───────────────────────────────────────
    async with async_guardrails() as client:
        prompt_check = await client.check_prompt(prompt, user_id=user_id)

    if prompt_check.is_blocked:
        log_blocked_event(
            blocked_by="guardrails_input",
            blocked_text=prompt,
            user_id=user_id,
            risk_level=prompt_check.overall_risk_level,
            score=prompt_check.score,
            is_safe=prompt_check.is_safe,
            model=request.model,
        )
        _write_guardrails_span(
            request_start_time=request_start_time,
            model=request.model,
            user_id=user_id,
            prompt=prompt,
            llm_response=None,
            guardrail_backend=env.guardrails_backend if env.guardrails_backend != "none" else None,
            prompt_check=prompt_check,
            response_check=None,
            status_code="BLOCKED",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "prompt_blocked",
                "message": "Your input violates content policies",
                "risk_level": prompt_check.overall_risk_level,
            },
        )

    # ── Step 2: Call LLM (auto-traced by Langtrace/OpenTelemetry) ─────────
    # Replace with a real LLM call when ready, e.g.:
    # from openai import AsyncOpenAI
    # openai_client = AsyncOpenAI(api_key=env.OPENAI_API_KEY)
    # completion = await openai_client.chat.completions.create(
    #     model=request.model,
    #     messages=[{"role": "user", "content": prompt}],
    # )
    # llm_response = completion.choices[0].message.content
    llm_response = f"This is a simulated response to: {prompt}"

    # ── Step 3: Guardrails on OUTPUT ──────────────────────────────────────
    async with async_guardrails() as client:
        response_check = await client.check_prompt(llm_response, user_id=user_id)

    if response_check.is_blocked:
        log_blocked_event(
            blocked_by="guardrails_output",
            blocked_text=llm_response,
            user_id=user_id,
            risk_level=response_check.overall_risk_level,
            score=response_check.score,
            is_safe=response_check.is_safe,
            model=request.model,
        )
        _write_guardrails_span(
            request_start_time=request_start_time,
            model=request.model,
            user_id=user_id,
            prompt=prompt,
            llm_response=llm_response,
            guardrail_backend=env.guardrails_backend if env.guardrails_backend != "none" else None,
            prompt_check=prompt_check,
            response_check=response_check,
            status_code="BLOCKED",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "response_blocked",
                "message": "The generated response violates content policies",
                "risk_level": response_check.overall_risk_level,
            },
        )

    # ── Step 4: Persist span with full audit data (success path) ──────────
    _write_guardrails_span(
        request_start_time=request_start_time,
        model=request.model,
        user_id=user_id,
        prompt=prompt,
        llm_response=llm_response,
        guardrail_backend=env.guardrails_backend if env.guardrails_backend != "none" else None,
        prompt_check=prompt_check,
        response_check=response_check,
        status_code="OK",
    )

    return ChatResponse(
        response=llm_response,
        prompt_risk_level=prompt_check.overall_risk_level,
        response_risk_level=response_check.overall_risk_level,
        model_used=request.model,
    )


@observability_router.get("/blocked-events", status_code=status.HTTP_200_OK)
def get_blocked_events(user_id: str | None = None, limit: int = 50):
    """Return recent blocked prompt/response events, optionally filtered by user_id."""
    with Session(engine) as session:
        stmt = select(LangtraceBlockedEvent).order_by(
            col(LangtraceBlockedEvent.created_at).desc()
        )
        if user_id:
            stmt = stmt.where(LangtraceBlockedEvent.user_id == user_id)
        events = session.exec(stmt.limit(limit)).all()
        return [
            {
                "id": e.id,
                "user_id": e.user_id,
                "blocked_by": e.blocked_by,
                "blocked_text": e.blocked_text,
                "risk_level": e.risk_level,
                "score": e.score,
                "is_safe": e.is_safe,
                "model": e.model,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]


@observability_router.post("/computedailysummary", status_code=status.HTTP_200_OK)
async def compute_daily_summary_endpoint(body: DailySummaryRequest):
    """Compute and persist daily per-model metrics for a given date (defaults to today UTC)."""
    from datetime import datetime

    date = datetime.strptime(body.date, "%Y-%m-%d") if body.date else None
    try:
        return persist_daily_summary(date=date) or []
    except Exception as exc:
        app_logger.warning("Daily summary failed for date: {} — {}", body.date, exc)
        return []


@router.post("/chat/conversation-context", response_model=ChatResponse)
async def chat_with_conversation_context(
    messages: list[dict[str, str]],
    user_id: str | None = None,
):
    """Example: Multi-turn conversation with context-aware guardrails.

    For chatbots with conversation history, use check_conversation()
    which understands context better than individual prompt checks.

    Example payload:
    ```json
    {
        "messages": [
            {"role": "user", "content": "What's machine learning?"},
            {"role": "assistant", "content": "It's a field of AI..."},
            {"role": "user", "content": "How can I use it maliciously?"}
        ],
        "user_id": "user-123"
    }
    ```
    """
    # Check full conversation context
    async with async_guardrails() as client:
        conversation_check = await client.check_conversation(messages, user_id=user_id)

        if conversation_check.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "conversation_blocked",
                    "message": "The conversation violates content policies",
                    "risk_level": conversation_check.overall_risk_level,
                },
            )

    # Extract latest user message
    latest_message = messages[-1]["content"] if messages else ""

    # Call LLM with full conversation history
    # from openai import AsyncOpenAI
    # openai_client = AsyncOpenAI(api_key=env.OPENAI_API_KEY)
    # completion = await openai_client.chat.completions.create(
    #     model="gpt-4",
    #     messages=messages,
    # )
    # llm_response = completion.choices[0].message.content

    llm_response = f"Simulated response to conversation ending with: {latest_message}"

    # Check response
    async with async_guardrails() as client:
        response_check = await client.check_prompt(llm_response)

        if response_check.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "response_blocked",
                    "message": "Generated response violates content policies",
                },
            )

    return ChatResponse(
        response=llm_response,
        prompt_risk_level=conversation_check.overall_risk_level,
        response_risk_level=response_check.overall_risk_level,
        model_used="gpt-4",
    )
