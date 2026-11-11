"""Allowlisted operational failures, safe to expose without exception details."""

_SAFE_MESSAGES: dict[str, str] = {
    "invalid_question": "The question must be a nonblank string.",
    "missing_snapshot": "No completed handbook snapshot is available.",
    "run_not_searchable": "The selected handbook snapshot is not searchable.",
    "database_error": "The handbook database operation failed.",
    "embedding_failed": "Question embedding failed.",
    "missing_api_key": "OpenAI credentials are not configured.",
    "configuration_failed": "RAG configuration is invalid or unsupported.",
    "context_budget_exceeded": "The request exceeds the configured token budget.",
    "invalid_citation_source": "Citation source metadata is invalid.",
    "invalid_model_output": "The model returned invalid structured output.",
    "model_refusal": "The model refused the request.",
    "incomplete_output": "The model response was incomplete.",
    "provider_context_limit": "The provider rejected the request context size.",
    "provider_failed": "The generation provider request failed.",
    "rag_failed": "The handbook answer operation failed.",
    "invalid_unicode": "The question contains unsupported Unicode text.",
}


class RagError(ValueError):
    """Stable code and sanitized message; unknown codes never expose raw input.

    Preserve diagnostic exceptions only as internal causes using ``raise ...
    from error``; callers must not render those causes to users or logs.
    """

    def __init__(self, reason_code: str) -> None:
        self.reason_code = (
            reason_code if reason_code in _SAFE_MESSAGES else "rag_failed"
        )
        super().__init__(_SAFE_MESSAGES[self.reason_code])
