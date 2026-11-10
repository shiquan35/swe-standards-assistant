"""Deterministic incomplete-ground-truth evidence coverage, not relevance."""

from collections.abc import Sequence
from typing import cast

_PROMPT_INJECTION_CATEGORY = "Prompt Injection and Instruction Handling"


def normalize(text: str) -> str:
    """Collapse whitespace and Unicode-casefold, preserving punctuation."""
    return " ".join(text.split()).casefold()


def evidence_metrics(
    expected: Sequence[str], chunks: Sequence[tuple[int, str]]
) -> dict[str, object]:
    """Match distinct whole statements within individual chunks at supplied ranks.

    The caller supplies only chunks within its chosen cutoff. Preserve the first
    original statement for each normalized value and every matching chunk rank.
    """
    statements: dict[str, str] = {}
    for statement in expected:
        statements.setdefault(normalize(statement), statement)
    normalized_chunks = [(rank, normalize(content)) for rank, content in chunks]
    matches: list[dict[str, object]] = []
    matched_count = 0
    for normalized, statement in statements.items():
        ranks = [rank for rank, content in normalized_chunks if normalized in content]
        matches.append({"statement": statement, "matching_ranks": ranks})
        matched_count += bool(ranks)

    expected_count = len(statements)
    return {
        "evidence_matches": matches,
        "expected_count": expected_count,
        "matched_count": matched_count,
        "evidence_hit_at_k": float(matched_count > 0) if expected_count else None,
        "evidence_recall_at_k": (
            matched_count / expected_count if expected_count else None
        ),
    }


def _summary(cases: Sequence[dict[str, object]]) -> dict[str, object]:
    """Macro-average already eligible, evidence-bearing case metrics."""
    count = len(cases)
    return {
        "eligible_case_count": count,
        "evidence_hit_at_k": (
            sum(cast(float, case["evidence_hit_at_k"]) for case in cases) / count
            if count
            else None
        ),
        "macro_evidence_recall_at_k": (
            sum(cast(float, case["evidence_recall_at_k"]) for case in cases) / count
            if count
            else None
        ),
    }


def aggregate_metrics(cases: Sequence[dict[str, object]]) -> dict[str, object]:
    """Separate core coverage from overlapping unanswerable/injection diagnostics.

    Inputs are validated case records with numeric evidence metrics whenever
    expected_count is positive. Empty categories remain visible with null scores.
    Diagnostic case_count includes all members; its metric denominator includes
    only members with evidence, regardless of answerability.
    """
    eligible = [
        case
        for case in cases
        if case["answerable"] is True
        and case["category"] != _PROMPT_INJECTION_CATEGORY
        and cast(int, case["expected_count"]) > 0
    ]
    categories = dict.fromkeys(cast(str, case["category"]) for case in cases)
    diagnostics: dict[str, object] = {}
    for name, members in (
        ("unanswerable", [case for case in cases if case["answerable"] is False]),
        (
            "prompt_injection",
            [case for case in cases if case["category"] == _PROMPT_INJECTION_CATEGORY],
        ),
    ):
        diagnostics[name] = {
            "case_count": len(members),
            **_summary(
                [case for case in members if cast(int, case["expected_count"]) > 0]
            ),
        }
    return {
        **_summary(eligible),
        "categories": {
            category: _summary(
                [case for case in eligible if case["category"] == category]
            )
            for category in categories
        },
        "diagnostics": diagnostics,
    }
