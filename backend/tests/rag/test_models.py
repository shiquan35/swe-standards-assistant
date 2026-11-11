"""Offline structural contracts, safe errors, and operator-configurable budgets."""

import importlib
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from pydantic_settings.sources import DotEnvSettingsSource

from app.rag import Citation, Claim, ModelOutput, RagError, RagResponse


def output(status: str = "answered") -> dict:
    return {
        "status": status,
        "claims": [{"text": "Use automated tests.", "citation_ids": [str(uuid4())]}],
        "clarifying_question": None,
        "reason": None,
        "unanswered_parts": [],
    }


def response(status: str = "answered") -> dict:
    payload = output(status)
    payload.update(
        citations=[
            {
                "chunk_id": payload["claims"][0]["citation_ids"][0],
                "title": "Handbook",
                "file_path": None,
                "heading_paths": [],
                "source_spans": [],
            }
        ],
        ingestion_run_id=str(uuid4()),
    )
    return payload


@pytest.mark.parametrize(
    "status", ["answered", "partial", "clarification_needed", "abstained"]
)
def test_all_statuses_round_trip(status: str) -> None:
    payload = response(status)
    if status == "partial":
        payload["unanswered_parts"] = ["Deployment frequency"]
    elif status == "clarification_needed":
        payload["clarifying_question"] = "Which project?"
        payload["unanswered_parts"] = ["Project-specific requirements"]
    elif status == "abstained":
        payload.update(
            claims=[], citations=[], reason="I don't know from this evidence."
        )
    result = RagResponse.model_validate(payload)
    assert isinstance(result, ModelOutput)
    assert isinstance(result.ingestion_run_id, UUID)
    assert result.model_dump(mode="json") == payload
    assert RagResponse.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("with_claims", [False, True])
def test_clarification_allows_optional_cited_claims(with_claims: bool) -> None:
    payload = response("clarification_needed")
    payload["clarifying_question"] = "Which project?"
    if not with_claims:
        payload.update(claims=[], citations=[])
    assert RagResponse.model_validate(payload).status == "clarification_needed"


@pytest.mark.parametrize(
    ("status", "changes"),
    [
        ("answered", {"claims": []}),
        ("answered", {"clarifying_question": "Which project?"}),
        ("answered", {"unanswered_parts": ["Unknown requirement"]}),
        ("answered", {"reason": ""}),
        ("partial", {}),
        ("partial", {"claims": [], "unanswered_parts": ["Unknown"]}),
        ("partial", {"unanswered_parts": ["Unknown"], "clarifying_question": "Why?"}),
        ("partial", {"unanswered_parts": ["Unknown"], "reason": "Unknown"}),
        ("partial", {"unanswered_parts": ["  "]}),
        ("clarification_needed", {}),
        ("clarification_needed", {"clarifying_question": " \n "}),
        ("clarification_needed", {"clarifying_question": "Why?", "reason": "Unknown"}),
        ("abstained", {"reason": "Unknown"}),
        ("abstained", {"claims": [], "reason": None}),
        ("abstained", {"claims": [], "reason": " \n "}),
        (
            "abstained",
            {"claims": [], "reason": "Unknown", "clarifying_question": "Why?"},
        ),
        (
            "abstained",
            {"claims": [], "reason": "Unknown", "unanswered_parts": ["Unknown"]},
        ),
        ("unsupported", {}),
    ],
)
def test_model_output_rejects_invalid_status_fields(status: str, changes: dict) -> None:
    with pytest.raises(ValidationError):
        ModelOutput.model_validate({**output(status), **changes})


@pytest.mark.parametrize("text", ["", " ", "\n\t"])
def test_claim_requires_nonblank_text(text: str) -> None:
    with pytest.raises(ValidationError):
        Claim(text=text, citation_ids=[uuid4()])


@pytest.mark.parametrize("ids", [[], ["invalid-uuid"]])
def test_claim_requires_valid_nonempty_citations(ids: list) -> None:
    with pytest.raises(ValidationError):
        Claim(text="Use tests.", citation_ids=ids)


def test_claim_rejects_duplicate_ids_after_uuid_parsing() -> None:
    chunk_id = uuid4()
    with pytest.raises(ValidationError, match="duplicate_claim_citation_ids"):
        Claim.model_validate(
            {"text": "Use tests.", "citation_ids": [chunk_id, str(chunk_id)]}
        )


def test_response_deduplicates_references_across_claims_not_sources() -> None:
    payload = response()
    payload["claims"].append(
        dict(payload["claims"][0], text="Run tests before merging.")
    )
    assert len(RagResponse.model_validate(payload).citations) == 1


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "wrong", "duplicate", "abstained"]
)
def test_response_requires_exact_unique_referenced_source_union(kind: str) -> None:
    payload = response()
    if kind == "missing":
        payload["citations"] = []
    elif kind == "extra":
        payload["citations"].append(
            dict(payload["citations"][0], chunk_id=str(uuid4()))
        )
    elif kind == "wrong":
        payload["citations"][0]["chunk_id"] = str(uuid4())
    elif kind == "duplicate":
        payload["citations"].append(dict(payload["citations"][0]))
    else:
        payload.update(status="abstained", claims=[], reason="I don't know.")
    with pytest.raises(ValidationError):
        RagResponse.model_validate(payload)


@pytest.mark.parametrize(("title", "path"), [(None, None), ("", None), (" \n", "\t")])
def test_citation_requires_nonblank_source_identity(title, path) -> None:
    payload = response()["citations"][0]
    with pytest.raises(ValidationError, match="invalid_citation_source"):
        Citation.model_validate({**payload, "title": title, "file_path": path})


def test_citation_accepts_path_only_and_preserves_provenance() -> None:
    payload = response()["citations"][0]
    payload.update(
        title=None,
        file_path="testing.md",
        heading_paths=[["Testing"]],
        source_spans=[[3, 5]],
    )
    assert Citation.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize("model", [Claim, Citation, ModelOutput, RagResponse])
def test_schema_requires_every_field_and_forbids_extras(model) -> None:
    payload = response()
    if model is Claim:
        payload = payload["claims"][0]
    elif model is Citation:
        payload = payload["citations"][0]
    elif model is ModelOutput:
        payload = output()
    schema = model.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    for field in payload:
        with pytest.raises(ValidationError):
            model.model_validate(
                {key: value for key, value in payload.items() if key != field}
            )
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "unexpected": "private text"})


def test_model_output_excludes_application_owned_fields() -> None:
    schema = ModelOutput.model_json_schema()
    assert "citations" not in schema["properties"]
    assert "ingestion_run_id" not in schema["properties"]
    assert schema["$defs"]["Claim"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "code",
    [
        "invalid_question",
        "missing_snapshot",
        "run_not_searchable",
        "database_error",
        "embedding_failed",
        "missing_api_key",
        "configuration_failed",
        "context_budget_exceeded",
        "invalid_citation_source",
        "invalid_model_output",
        "model_refusal",
        "incomplete_output",
        "provider_context_limit",
        "provider_failed",
        "rag_failed",
        "invalid_unicode",
    ],
)
def test_safe_error_codes(code: str) -> None:
    error = RagError(code)
    assert isinstance(error, ValueError)
    assert error.reason_code == code
    assert str(error).strip()


def test_unknown_error_is_generic_and_cause_is_internal_only() -> None:
    private = "private question credentials provider response"
    try:
        raise RagError(private) from RuntimeError(private)
    except RagError as error:
        assert error.reason_code == "rag_failed"
        assert str(error) == str(RagError("rag_failed"))
        assert private not in repr(error)
        assert isinstance(error.__cause__, RuntimeError)


@pytest.fixture
def env_class(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", lambda self: {})
    monkeypatch.setenv("DB_FULL_CONNECTION_STRING", "postgresql://unused")
    for name in [
        "OPENAI_CHAT_MODEL",
        "RAG_MAX_INPUT_TOKENS",
        "RAG_MAX_OUTPUT_TOKENS",
        "RAG_TOKEN_SAFETY_MARGIN",
        "RAG_MODEL_CONTEXT_WINDOW",
    ]:
        monkeypatch.delenv(name, raising=False)
    return importlib.import_module("app.core.env").Env


def test_rag_configuration_defaults(env_class) -> None:
    settings = env_class()
    assert settings.OPENAI_CHAT_MODEL == "gpt-6-luna"
    assert settings.RAG_MAX_INPUT_TOKENS == 32000
    assert settings.RAG_MAX_OUTPUT_TOKENS == 4096
    assert settings.RAG_TOKEN_SAFETY_MARGIN == 0.20
    assert settings.RAG_MODEL_CONTEXT_WINDOW == 1050000


@pytest.mark.parametrize("margin", ["0", "1", "0.35"])
def test_operator_overrides(
    env_class, monkeypatch: pytest.MonkeyPatch, margin: str
) -> None:
    monkeypatch.setenv("RAG_TOKEN_SAFETY_MARGIN", margin)
    monkeypatch.setenv("RAG_MODEL_CONTEXT_WINDOW", "128000")
    monkeypatch.setenv("RAG_MAX_INPUT_TOKENS", "16000")
    monkeypatch.setenv("RAG_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "operator-selected-model")
    settings = env_class()
    assert settings.RAG_TOKEN_SAFETY_MARGIN == float(margin)
    assert settings.RAG_MODEL_CONTEXT_WINDOW == 128000
    assert settings.RAG_MAX_INPUT_TOKENS == 16000
    assert settings.RAG_MAX_OUTPUT_TOKENS == 2048
    assert settings.OPENAI_CHAT_MODEL == "operator-selected-model"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RAG_TOKEN_SAFETY_MARGIN", "-0.01"),
        ("RAG_TOKEN_SAFETY_MARGIN", "1.01"),
        ("RAG_TOKEN_SAFETY_MARGIN", "nan"),
        ("RAG_TOKEN_SAFETY_MARGIN", "inf"),
        ("RAG_MODEL_CONTEXT_WINDOW", "0"),
        ("RAG_MODEL_CONTEXT_WINDOW", "-1"),
        ("RAG_MODEL_CONTEXT_WINDOW", "1.5"),
        ("RAG_MAX_INPUT_TOKENS", "0"),
        ("RAG_MAX_OUTPUT_TOKENS", "-1"),
    ],
)
def test_invalid_rag_configuration(
    env_class, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        env_class()
