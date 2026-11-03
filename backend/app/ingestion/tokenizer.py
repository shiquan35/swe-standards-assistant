"""Exact literal-text tokenization for text-embedding-3-small, without API calls."""

import re

import tiktoken

from app.ingestion.chunk_models import ChunkingError


def validate_unicode(text: str) -> None:
    """Reject lone surrogates rather than allowing a tokenizer to replace them."""
    if re.search(r"[\ud800-\udfff]", text):
        raise ChunkingError("invalid_unicode")


class TiktokenTokenizer:
    """cl100k_base; authored special-token spellings are always ordinary text.

    The first tiktoken cache miss may download its vocabulary. Subsequent
    encodes use the loaded local encoding and never call an embedding service.
    """

    def __init__(self) -> None:
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def encode(self, text: str) -> list[int]:
        validate_unicode(text)
        return self._encoding.encode(text, allowed_special=set(), disallowed_special=())

    def count(self, text: str) -> int:
        """Independently encode the exact complete string, not a sum of parts."""
        return len(self.encode(text))
