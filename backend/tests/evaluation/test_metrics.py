"""Offline contracts for incomplete-ground-truth evidence coverage."""

import pytest

from app.evaluation.metrics import aggregate_metrics, evidence_metrics, normalize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Require\tTESTS.\n\r Before   merging!  ", "require tests. before merging!"),
        ("Straße\u00a0STRASSE", "strasse strasse"),
        ("\t\n\u2003", ""),
        ("API: don't remove-punctuation!", "api: don't remove-punctuation!"),
    ],
)
def test_normalize(text: str, expected: str) -> None:
    assert normalize(text) == expected
    assert normalize(normalize(text)) == expected


def test_matching_normalizes_and_preserves_original_statements_and_ranks() -> None:
    assert evidence_metrics(
        ["Require TESTS.", "Review changes."],
        [
            (2, "Always require\n tests. Before merging."),
            (5, "REQUIRE TESTS. Review\tchanges."),
            (9, "Unrelated content."),
        ],
    ) == {
        "evidence_matches": [
            {"statement": "Require TESTS.", "matching_ranks": [2, 5]},
            {"statement": "Review changes.", "matching_ranks": [5]},
        ],
        "expected_count": 2,
        "matched_count": 2,
        "evidence_hit_at_k": 1.0,
        "evidence_recall_at_k": 1.0,
    }


def test_statement_split_across_chunks_does_not_match() -> None:
    result = evidence_metrics(
        ["Require tests before merging."],
        [(1, "Require tests"), (2, "before merging.")],
    )
    assert result == {
        "evidence_matches": [
            {"statement": "Require tests before merging.", "matching_ranks": []}
        ],
        "expected_count": 1,
        "matched_count": 0,
        "evidence_hit_at_k": 0.0,
        "evidence_recall_at_k": 0.0,
    }


def test_duplicates_are_normalized_and_repeated_chunk_matches_count_once() -> None:
    result = evidence_metrics(
        ["Straße policy.", " STRASSE\nPOLICY. ", "Other evidence."],
        [(1, "STRASSE policy. Straße policy."), (3, "Straße policy.")],
    )
    assert result == {
        "evidence_matches": [
            {"statement": "Straße policy.", "matching_ranks": [1, 3]},
            {"statement": "Other evidence.", "matching_ranks": []},
        ],
        "expected_count": 2,
        "matched_count": 1,
        "evidence_hit_at_k": 1.0,
        "evidence_recall_at_k": 0.5,
    }


def test_matching_preserves_punctuation() -> None:
    result = evidence_metrics(["Require tests."], [(1, "Require tests!")])
    assert result["matched_count"] == 0
    assert result["evidence_hit_at_k"] == 0.0
    assert result["evidence_recall_at_k"] == 0.0


@pytest.mark.parametrize("chunks", [[], [(1, "Some retrieved content.")]])
def test_empty_evidence_has_null_metrics(chunks: list[tuple[int, str]]) -> None:
    assert evidence_metrics([], chunks) == {
        "evidence_matches": [],
        "expected_count": 0,
        "matched_count": 0,
        "evidence_hit_at_k": None,
        "evidence_recall_at_k": None,
    }


def test_no_chunks_is_a_miss_when_evidence_exists() -> None:
    result = evidence_metrics(["Require tests."], [])
    assert result["expected_count"] == 1
    assert result["matched_count"] == 0
    assert result["evidence_hit_at_k"] == 0.0
    assert result["evidence_recall_at_k"] == 0.0


def _case(
    category: str,
    answerable: bool,
    expected_count: int,
    hit: float | None,
    recall: float | None,
) -> dict[str, object]:
    return {
        "category": category,
        "answerable": answerable,
        "expected_count": expected_count,
        "evidence_hit_at_k": hit,
        "evidence_recall_at_k": recall,
    }


def _summary(count: int, hit: float | None, recall: float | None) -> dict[str, object]:
    return {
        "eligible_case_count": count,
        "evidence_hit_at_k": hit,
        "macro_evidence_recall_at_k": recall,
    }


def test_core_macro_and_category_denominators_exclude_diagnostics() -> None:
    injection = "Prompt Injection and Instruction Handling"
    result = aggregate_metrics(
        [
            _case("Coding", True, 1, 0.0, 0.0),
            _case("Coding", True, 4, 1.0, 0.5),
            _case("API", True, 1, 1.0, 1.0),
            _case("Coding", False, 0, None, None),
            _case("No evidence", True, 0, None, None),
            _case(injection, True, 2, 0.0, 0.0),
            _case(injection, False, 0, None, None),
        ]
    )
    assert result == {
        **_summary(3, 2 / 3, 0.5),
        "categories": {
            "Coding": _summary(2, 0.5, 0.25),
            "API": _summary(1, 1.0, 1.0),
            "No evidence": _summary(0, None, None),
            injection: _summary(0, None, None),
        },
        "diagnostics": {
            "unanswerable": {"case_count": 2, **_summary(0, None, None)},
            "prompt_injection": {"case_count": 2, **_summary(1, 0.0, 0.0)},
        },
    }


def test_diagnostics_average_only_evidence_bearing_cases_and_can_overlap() -> None:
    injection = "Prompt Injection and Instruction Handling"
    assert aggregate_metrics(
        [
            _case("Unsupported", False, 0, None, None),
            _case("Unsupported", False, 2, 1.0, 0.5),
            _case(injection, False, 1, 0.0, 0.0),
            _case(injection, True, 3, 1.0, 1.0),
            _case(injection, True, 0, None, None),
        ]
    ) == {
        **_summary(0, None, None),
        "categories": {
            "Unsupported": _summary(0, None, None),
            injection: _summary(0, None, None),
        },
        "diagnostics": {
            "unanswerable": {"case_count": 3, **_summary(2, 0.5, 0.25)},
            "prompt_injection": {"case_count": 3, **_summary(2, 0.5, 0.5)},
        },
    }


def test_empty_aggregates_have_null_metrics_and_explicit_zero_counts() -> None:
    assert aggregate_metrics([]) == {
        **_summary(0, None, None),
        "categories": {},
        "diagnostics": {
            "unanswerable": {"case_count": 0, **_summary(0, None, None)},
            "prompt_injection": {"case_count": 0, **_summary(0, None, None)},
        },
    }
