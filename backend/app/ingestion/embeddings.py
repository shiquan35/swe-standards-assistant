"""Ordered, bounded embedding requests, independent of persistence and caching."""

import logging
import math
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types import CreateEmbeddingResponse
from pydantic import SecretStr

from app.ingestion.chunk_models import Tokenizer
from app.ingestion.tokenizer import TiktokenTokenizer

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_INPUT_TOKENS = 8192
MAX_BATCH_INPUTS = 2048
MAX_BATCH_TOKENS = 300_000
SDK_MAX_RETRIES = 2
SDK_TIMEOUT_SECONDS = 30.0

_private_request: ContextVar[bool] = ContextVar(
    "embedding_private_request", default=False
)


class _ProviderLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_request.get()


@contextmanager
def _without_provider_logs() -> Iterator[None]:
    """SDK debug logs include request bodies; silence them in this context only."""
    names = {"openai", "openai._base_client", "httpx", "httpcore"}
    names.update(
        name
        for name in list(logging.Logger.manager.loggerDict)
        if name.startswith(("openai.", "httpx.", "httpcore."))
    )
    loggers = [logging.getLogger(name) for name in names]
    guard = _ProviderLogFilter()
    token = _private_request.set(True)
    try:
        for logger in loggers:
            logger.addFilter(guard)
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(guard)
        _private_request.reset(token)


class EmbeddingError(ValueError):
    """Content-free failure code; never retains provider messages or bodies."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _request_failure(error: Exception) -> tuple[str, int | None, str | None]:
    """Classify SDK failures without retaining messages, bodies, or headers."""
    if isinstance(error, APITimeoutError):
        return "request_timeout", None, None
    if isinstance(error, APIConnectionError):
        return "connection_failed", None, None
    if isinstance(error, APIStatusError):
        status = error.status_code
        # Provider codes are untrusted strings: emit only known literal codes.
        code = (
            error.code
            if error.code
            in (
                "insufficient_quota",
                "rate_limit_exceeded",
                "invalid_api_key",
                "model_not_found",
                "billing_hard_limit_reached",
            )
            else None
        )
        if code in {"insufficient_quota", "billing_hard_limit_reached"}:
            reason = "quota_exceeded"
        else:
            reason = {
                400: "invalid_request",
                401: "authentication_failed",
                403: "permission_denied",
                404: "model_unavailable",
                429: "rate_limited",
            }.get(
                status, "provider_server_error" if status >= 500 else "request_failed"
            )
        return reason, status, code
    return "request_failed", None, None


class EmbeddingsEndpoint(Protocol):
    def create(
        self,
        *,
        input: list[str],
        model: str,
        dimensions: int,
        encoding_format: Literal["float"],
    ) -> CreateEmbeddingResponse: ...


class EmbeddingClient(Protocol):
    @property
    def embeddings(self) -> EmbeddingsEndpoint: ...


class EmbeddingService:
    """Reuse one lazy client; callers own completed-run DB cache lookups.

    Injected clients own their retry/timeout configuration. Injected tokenizers
    must implement the literal cl100k_base encoding contract. Inputs are fully
    validated before the first request; no truncation, splitting, or text logs.
    """

    def __init__(
        self,
        *,
        client: EmbeddingClient | None = None,
        tokenizer: Tokenizer | None = None,
        api_key: SecretStr | None = None,
    ) -> None:
        self._client = client
        self._tokenizer = tokenizer
        self._api_key = api_key

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one validated vector per input, preserving the input order."""
        if not isinstance(texts, Sequence) or isinstance(
            texts, (str, bytes, bytearray)
        ):
            raise EmbeddingError("invalid_input_sequence")
        inputs = list(texts)
        if not inputs:
            return []

        for text in inputs:
            if not isinstance(text, str):
                raise EmbeddingError("invalid_input_type")
            if not text:
                raise EmbeddingError("empty_input")
            try:
                text.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise EmbeddingError("invalid_unicode") from None

        counts: list[int] = []
        try:
            if self._tokenizer is None:
                self._tokenizer = TiktokenTokenizer()
            counts = [len(self._tokenizer.encode(text)) for text in inputs]
        except Exception:
            raise EmbeddingError("tokenization_failed") from None
        if any(count == 0 for count in counts):
            raise EmbeddingError("empty_input_tokens")
        if any(count > MAX_INPUT_TOKENS for count in counts):
            raise EmbeddingError("input_token_limit")

        vectors: list[list[float]] = []
        batch: list[str] = []
        batch_tokens = 0
        for text, count in zip(inputs, counts, strict=True):
            if (
                len(batch) == MAX_BATCH_INPUTS
                or batch_tokens + count > MAX_BATCH_TOKENS
            ):
                vectors.extend(self._embed_batch(batch))
                batch = []
                batch_tokens = 0
            batch.append(text)
            batch_tokens += count
        vectors.extend(self._embed_batch(batch))
        return vectors

    def _get_client(self) -> EmbeddingClient:
        if self._client is None:
            key = self._api_key
            if key is None:
                try:
                    from app.core.env import env

                    key = env.OPENAI_API_KEY
                except Exception:
                    raise EmbeddingError("configuration_failed") from None
            if key is None or not key.get_secret_value().strip():
                raise EmbeddingError("missing_api_key")
            try:
                with _without_provider_logs():
                    self._client = OpenAI(
                        api_key=key.get_secret_value(),
                        max_retries=SDK_MAX_RETRIES,
                        timeout=SDK_TIMEOUT_SECONDS,
                    )
            except Exception:
                raise EmbeddingError("client_initialization_failed") from None
        return self._client

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        # Standard-library logging avoids importing application settings here.
        logger = logging.getLogger(__name__)
        started = time.perf_counter()
        logger.debug(
            "embedding_batch_started model=%s inputs=%d dimensions=%d",
            EMBEDDING_MODEL,
            len(texts),
            EMBEDDING_DIMENSIONS,
        )
        try:
            with _without_provider_logs():
                response = client.embeddings.create(
                    input=texts,
                    model=EMBEDDING_MODEL,
                    dimensions=EMBEDDING_DIMENSIONS,
                    encoding_format="float",
                )
        except Exception as error:
            # Do not log or chain SDK failures: messages can contain input/keys.
            reason, status, code = _request_failure(error)
            logger.error(
                "embedding_batch_failed model=%s inputs=%d reason=%s status_code=%s error_code=%s",
                EMBEDDING_MODEL,
                len(texts),
                reason,
                status,
                code,
            )
            raise EmbeddingError(reason) from None
        try:
            vectors = self._validate_response(response, len(texts))
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingError("invalid_response") from None
        logger.debug(
            "embedding_batch_completed model=%s inputs=%d dimensions=%d duration_ms=%.2f",
            EMBEDDING_MODEL,
            len(texts),
            EMBEDDING_DIMENSIONS,
            (time.perf_counter() - started) * 1000,
        )
        return vectors

    @staticmethod
    def _validate_response(
        response: CreateEmbeddingResponse, count: int
    ) -> list[list[float]]:
        if not isinstance(response.data, list) or len(response.data) != count:
            raise EmbeddingError("response_count")
        ordered: list[list[float]] = [[] for _ in range(count)]
        seen: set[int] = set()
        for item in response.data:
            index = item.index
            if type(index) is not int or not 0 <= index < count or index in seen:
                raise EmbeddingError("response_index")
            seen.add(index)
            vector = item.embedding
            if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
                raise EmbeddingError("response_dimensions")
            normalized: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EmbeddingError("response_vector")
                try:
                    number = float(value)
                except (OverflowError, ValueError):
                    raise EmbeddingError("response_vector") from None
                if not math.isfinite(number):
                    raise EmbeddingError("response_vector")
                normalized.append(number)
            ordered[index] = normalized
        return ordered
