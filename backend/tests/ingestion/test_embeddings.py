"""Offline embedding contracts: no DB, dotenv reads, or live provider calls."""

import importlib
import logging
import socket
import traceback
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Literal, cast

import httpx
import pytest
import tiktoken
from openai import OpenAI
from openai.types import CreateEmbeddingResponse
from pydantic import SecretStr, ValidationError
from pydantic_settings.sources import DotEnvSettingsSource

from app.ingestion import embeddings
from app.ingestion.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EmbeddingError,
    EmbeddingService,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Network access is forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    # Importing app.core.env below must never read the real dotenv file.
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", lambda self: {})
    monkeypatch.setenv("DB_FULL_CONNECTION_STRING", "sqlite://")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)


class FakeTokenizer:
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.counts = counts or {}
        self.texts: list[str] = []

    def encode(self, text: str) -> list[int]:
        self.texts.append(text)
        return [0] * self.counts.get(text, 1)


def response_for(
    indices: list[object], vectors: list[object]
) -> CreateEmbeddingResponse:
    return cast(
        CreateEmbeddingResponse,
        SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=vector)
                for index, vector in zip(indices, vectors, strict=True)
            ]
        ),
    )


class FakeClient:
    def __init__(self) -> None:
        self.embeddings = self
        self.calls: list[list[str]] = []
        self.respond: Callable[[list[str]], CreateEmbeddingResponse] = self._respond

    def _respond(self, texts: list[str]) -> CreateEmbeddingResponse:
        # Reverse provider order to exercise per-batch index restoration.
        indices = list(reversed(range(len(texts))))
        return response_for(
            list(indices),
            [[float(i)] * EMBEDDING_DIMENSIONS for i in indices],
        )

    def create(
        self,
        *,
        input: list[str],
        model: str,
        dimensions: int,
        encoding_format: Literal["float"],
    ) -> CreateEmbeddingResponse:
        assert model == "text-embedding-3-small"
        assert dimensions == 1536
        assert encoding_format == "float"
        self.calls.append(list(input))
        return self.respond(input)


def test_empty_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        pytest.fail("Empty inputs must not initialize a tokenizer")

    monkeypatch.setattr(embeddings, "TiktokenTokenizer", forbidden)
    service = EmbeddingService()
    assert service.embed_texts([]) == []
    assert service.embed_texts(()) == []
    assert service._client is None


def test_batch_logs_shapes_not_input_or_vectors(caplog) -> None:
    client = FakeClient()
    with caplog.at_level(logging.DEBUG, logger=embeddings.__name__):
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
            ["PRIVATE_SOURCE_SENTINEL"]
        )
    assert "embedding_batch_started" in caplog.text
    assert "embedding_batch_completed" in caplog.text
    assert "inputs=1 dimensions=1536" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "PRIVATE_SOURCE_SENTINEL" not in caplog.text


def test_failure_logs_safe_reason_not_provider_body(caplog) -> None:
    client = FakeClient()

    def fail(_texts):
        raise RuntimeError("PRIVATE_PROVIDER_BODY")

    client.respond = fail
    with caplog.at_level(logging.DEBUG, logger=embeddings.__name__):
        with pytest.raises(EmbeddingError, match="request_failed"):
            EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
                ["PRIVATE_SOURCE_SENTINEL"]
            )
    assert "embedding_batch_failed" in caplog.text
    assert "reason=request_failed" in caplog.text
    assert "PRIVATE_PROVIDER_BODY" not in caplog.text
    assert "PRIVATE_SOURCE_SENTINEL" not in caplog.text


@pytest.mark.parametrize(
    "texts", [None, 42, "secret", b"bytes", bytearray(b"x"), {"x"}, {"a": "b"}]
)
def test_rejects_non_sequences(texts: object) -> None:
    with pytest.raises(EmbeddingError, match="^invalid_input_sequence$"):
        EmbeddingService().embed_texts(texts)  # type: ignore[arg-type]


def test_rejects_generator() -> None:
    def texts() -> Iterator[str]:
        yield "a"

    with pytest.raises(EmbeddingError, match="^invalid_input_sequence$"):
        EmbeddingService().embed_texts(texts())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value, reason",
    [
        (None, "invalid_input_type"),
        (1, "invalid_input_type"),
        (True, "invalid_input_type"),
        (b"x", "invalid_input_type"),
        (["x"], "invalid_input_type"),
        ("", "empty_input"),
        ("\ud800", "invalid_unicode"),
        ("x\udfff", "invalid_unicode"),
        ("\ud83d\ude00", "invalid_unicode"),
    ],
)
def test_rejects_bad_items_before_any_request(value: object, reason: str) -> None:
    client = FakeClient()
    with pytest.raises(EmbeddingError, match=f"^{reason}$"):
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
            ["valid"] * 2049 + [value]  # type: ignore[arg-type]
        )
    assert client.calls == []


def test_singleton_and_reuse() -> None:
    client = FakeClient()
    service = EmbeddingService(client=client, tokenizer=FakeTokenizer())
    assert service.embed_texts(("question",)) == [[0.0] * 1536]
    assert service.embed_texts(["a", "b", "a"]) == [[float(i)] * 1536 for i in range(3)]
    assert client.calls == [["question"], ["a", "b", "a"]]


@pytest.mark.parametrize(
    "size, expected", [(2048, [2048]), (2049, [2048, 1]), (4097, [2048, 2048, 1])]
)
def test_input_count_batches(size: int, expected: list[int]) -> None:
    client = FakeClient()
    texts = [str(i) for i in range(size)]
    result = EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
        texts
    )
    assert [len(batch) for batch in client.calls] == expected
    assert [text for batch in client.calls for text in batch] == texts
    assert [v[0] for v in result] == [float(i) for n in expected for i in range(n)]


def test_exact_batch_token_boundary_and_overflow() -> None:
    client = FakeClient()
    tokenizer = FakeTokenizer({"large": 8192, "remainder": 5088})
    texts = ["large"] * 36 + ["remainder", "next", "large"]
    vectors = EmbeddingService(client=client, tokenizer=tokenizer).embed_texts(texts)
    assert client.calls == [texts[:37], texts[37:]]
    assert len(vectors) == len(texts)


def test_greedy_packing_above_aggregate_limit() -> None:
    client = FakeClient()
    service = EmbeddingService(client=client, tokenizer=FakeTokenizer({"x": 8192}))
    assert len(service.embed_texts(["x"] * 74)) == 74
    assert [len(batch) for batch in client.calls] == [36, 36, 2]


@pytest.mark.parametrize(
    "count, reason", [(0, "empty_input_tokens"), (8193, "input_token_limit")]
)
def test_bad_token_count_preflight(count: int, reason: str) -> None:
    client = FakeClient()
    with pytest.raises(EmbeddingError, match=f"^{reason}$"):
        EmbeddingService(
            client=client, tokenizer=FakeTokenizer({"bad": count})
        ).embed_texts(["good"] * 2049 + ["bad"])
    assert client.calls == []


def test_literal_exact_encoding() -> None:
    texts = ["<|endoftext|><|fim_prefix|>", "😀漢字e\u0301\n\t ", " ", "hello"]
    client = FakeClient()
    service = EmbeddingService(client=client)
    service.embed_texts(texts)
    assert client.calls == [texts]
    encoding = tiktoken.get_encoding("cl100k_base")
    assert service._tokenizer is not None
    for text in texts:
        tokens = service._tokenizer.encode(text)
        assert tokens == encoding.encode(
            text, allowed_special=set(), disallowed_special=()
        )
        assert encoding.decode(tokens) == text


def test_real_tokenizer_limit() -> None:
    client = FakeClient()
    service = EmbeddingService(client=client)
    # Each space-delimited 'a' adds exactly one cl100k_base token.
    assert len(tiktoken.get_encoding("cl100k_base").encode("a " * 8191 + "a")) == 8192
    assert len(service.embed_texts(["a " * 8191 + "a"])) == 1
    with pytest.raises(EmbeddingError, match="^input_token_limit$"):
        service.embed_texts(["a " * 8192 + "a"])
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "indices", [[0, 0], [-1, 1], [0, 2], [False, 1], [0.0, 1], ["0", 1]]
)
def test_bad_response_indices(indices: list[object]) -> None:
    client = FakeClient()
    client.respond = lambda texts: response_for(indices, [[0.0] * 1536] * 2)
    with pytest.raises(EmbeddingError, match="^response_index$"):
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
            ["a", "b"]
        )


@pytest.mark.parametrize("count", [0, 1, 3])
def test_bad_response_count(count: int) -> None:
    client = FakeClient()
    client.respond = lambda texts: response_for(
        list(range(count)), [[0.0] * 1536] * count
    )
    with pytest.raises(EmbeddingError, match="^response_count$"):
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
            ["a", "b"]
        )


@pytest.mark.parametrize(
    "vector", [[], [0.0] * 1535, [0.0] * 1537, "secret", None, (0.0,) * 1536]
)
def test_bad_response_dimensions(vector: object) -> None:
    client = FakeClient()
    client.respond = lambda texts: response_for([0], [vector])
    with pytest.raises(EmbeddingError, match="^response_dimensions$"):
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(["a"])


@pytest.mark.parametrize(
    "value",
    [
        True,
        "1.0",
        None,
        complex(1, 2),
        float("nan"),
        float("inf"),
        -float("inf"),
        10**400,
    ],
)
def test_bad_vector_values(value: object) -> None:
    client = FakeClient()
    client.respond = lambda texts: response_for([0], [[value] + [0.0] * 1535])
    with pytest.raises(EmbeddingError, match="^response_vector$"):
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(["a"])


def test_finite_integer_values_normalize_to_float() -> None:
    client = FakeClient()
    client.respond = lambda texts: response_for([0], [[-1, 0, 1] + [0] * 1533])
    vector = EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
        ["a"]
    )[0]
    assert vector[:3] == [-1.0, 0.0, 1.0]
    assert all(type(value) is float for value in vector)


@pytest.mark.parametrize(
    "response", [None, {}, SimpleNamespace(data=[None]), SimpleNamespace(data=None)]
)
def test_malformed_response(response: object) -> None:
    client = FakeClient()
    client.respond = lambda texts: cast(CreateEmbeddingResponse, response)
    with pytest.raises(EmbeddingError) as caught:
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(["a"])
    assert caught.value.reason_code in {"invalid_response", "response_count"}


def test_failure_stops_batches_and_sanitizes_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeClient()
    secret = "private-source-vector-api-key"

    def fail(_texts: list[str]) -> CreateEmbeddingResponse:
        logging.getLogger("openai._base_client").debug(secret)
        raise RuntimeError(secret)

    client.respond = fail
    caplog.set_level(logging.DEBUG)
    with pytest.raises(EmbeddingError) as caught:
        EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
            [secret] * 2049
        )
    assert caught.value.reason_code == "request_failed"
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert secret not in caplog.text
    assert len(client.calls) == 1
    logging.getLogger("openai._base_client").debug("restored")
    assert "restored" in caplog.text


def test_tokenizer_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise RuntimeError("private source")

    monkeypatch.setattr(embeddings, "TiktokenTokenizer", fail)
    with pytest.raises(EmbeddingError, match="^tokenization_failed$") as caught:
        EmbeddingService().embed_texts(["a"])
    assert "private source" not in "".join(traceback.format_exception(caught.value))


def test_settings_optional_secret_and_fixed_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("app.core.env")
    settings = module.Env(_env_file=None)
    assert settings.OPENAI_API_KEY is None
    assert settings.OPENAI_EMBEDDING_MODEL == EMBEDDING_MODEL
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    settings = module.Env(_env_file=None)
    assert isinstance(settings.OPENAI_API_KEY, SecretStr)
    assert settings.OPENAI_API_KEY.get_secret_value() == "private-key"
    assert "private-key" not in repr(settings)
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "other-model")
    with pytest.raises(ValidationError):
        module.Env(_env_file=None)


def test_lazy_default_client_configuration_and_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> FakeClient:
        calls.append(kwargs)
        return client

    monkeypatch.setattr(embeddings, "OpenAI", factory)
    service = EmbeddingService(
        api_key=SecretStr("private-key"), tokenizer=FakeTokenizer()
    )
    assert calls == []
    service.embed_texts(["a"])
    service.embed_texts(["b"])
    assert calls == [{"api_key": "private-key", "max_retries": 2, "timeout": 30.0}]


@pytest.mark.parametrize("key", [None, SecretStr(""), SecretStr("  ")])
def test_missing_key_deferred_until_request(
    key: SecretStr | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("app.core.env")
    monkeypatch.setattr(module.env, "OPENAI_API_KEY", key)
    service = EmbeddingService(tokenizer=FakeTokenizer())
    assert service.embed_texts([]) == []
    with pytest.raises(EmbeddingError, match="^missing_api_key$"):
        service.embed_texts(["a"])


def test_key_loaded_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("app.core.env")
    monkeypatch.setattr(module.env, "OPENAI_API_KEY", SecretStr("configured-key"))
    client = FakeClient()

    def factory(**kwargs: object) -> FakeClient:
        assert kwargs["api_key"] == "configured-key"
        return client

    monkeypatch.setattr(embeddings, "OpenAI", factory)
    assert EmbeddingService(tokenizer=FakeTokenizer()).embed_texts(["a"]) == [
        [0.0] * 1536
    ]


def test_client_initialization_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(**_kwargs: object) -> None:
        raise RuntimeError("private-key")

    monkeypatch.setattr(embeddings, "OpenAI", factory)
    with pytest.raises(
        EmbeddingError, match="^client_initialization_failed$"
    ) as caught:
        EmbeddingService(
            api_key=SecretStr("private-key"), tokenizer=FakeTokenizer()
        ).embed_texts(["a"])
    assert "private-key" not in "".join(traceback.format_exception(caught.value))


def test_sdk_retry_exhaustion_offline(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    requests: list[httpx.Request] = []
    secret = "private-source-key"

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429, json={"error": {"message": "private-source-key", "type": "rate_limit"}}
        )

    monkeypatch.setattr("openai._base_client.time.sleep", lambda seconds: None)
    caplog.set_level(logging.DEBUG)
    with OpenAI(
        api_key="private-source-key",
        max_retries=2,
        timeout=30.0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        with pytest.raises(EmbeddingError, match="^request_failed$") as caught:
            EmbeddingService(client=client, tokenizer=FakeTokenizer()).embed_texts(
                [secret]
            )
    assert len(requests) == 3
    assert requests[0].extensions["timeout"] == {
        "connect": 30.0,
        "read": 30.0,
        "write": 30.0,
        "pool": 30.0,
    }
    assert "private-source-key" not in "".join(traceback.format_exception(caught.value))
    assert "private-source-key" not in caplog.text
