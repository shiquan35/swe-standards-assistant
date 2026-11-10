# Retrieval Evaluation

*Co-written by Shi Quan and LLM.*

To assess the following:

* To determine whether the vector search can consistently find the correct information.
* Which chunking strategy performs best?
* How does changing `top_k`, chunk size and overlap affect results?

## Preparation

- test dataset in JSON
- define evaluation metrics
- design experiments

## Experiment

| Experiment | Strategy      | Tokens | Overlap | Top_k |
| ---------- | ------------- | ------ | ------- | ----- |
| 1.1        | fixed         | 200    | 0       | 3     |
| 1.2        | fixed         | 200    | 0       | 5     |
| 1.3        | fixed_overlap | 200    | 40      | 3     |
| 1.4        | fixed_overlap | 200    | 40      | 5     |
| 1.5        | heading_aware | 200    | 40      | 3     |
| 1.6        | heading_aware | 200    | 40      | 5     |

## Experiment Considerations (Evaluation Runner)

Since "known_relevant_sources" and "expected_evidence" in `retrieval_cases.json` are meant to be non-exhaustive, evaluation should report:

- **Automated evidence matching**: Did the retrieved chunks contain the known evidence statements?
- **Manual relevance assessment**: Were the retrieved chunks useful for answering the question, even if the known evidence did not specify them?

This is to avoid penalising the chunking strategies even though they retrieved useful content from sources I did not list.

## Evaluation Metrics

The following metrics are used to evaluate retrieval performance:

### 1. EvidenceHit@K

Measures whether at least one expected evidence statement was found within the top-K retrieved chunks.

- **1:** At least one expected statement was found.
- **0:** No expected statements were found.

### 2. EvidenceRecall@K

Measures the proportion of expected evidence statements found within the top-K retrieved chunks.

**Formula:**

EvidenceRecall@K = Matched evidence statements / Total expected evidence statements

For example, retrieving 3 out of 4 expected statements gives a recall of 75%.

### 3. Human Hit@K and Mean Reciprocal Rank (MRR)

These metrics are planned but have not yet been evaluated.

- **Human Hit@K:** Measures whether at least one genuinely relevant chunk was retrieved.
- **MRR:** Measures how highly the first relevant chunk appears in the retrieval results.

These require manual relevance assessments.

### Evaluation Limitations

- Expected evidence statements are non-exhaustive.
- Evidence must appear entirely within a single chunk to count as a match.
- Unanswerable and prompt-injection test cases are evaluated separately.
- Results measure known-evidence coverage, not overall retrieval quality.

## Evaluation findings retrieval-20261110T083627933914Z

Provenance:

- Dataset SHA-256: `5460bc60b6f8e3108d79506b51855f8ccb28633f03ce93a50d672c1ab3b9b4aa`.
- Shared source-only SHA-256: `10995f5f1a73558e26b99e6733b2bf921c8ea73e0aa556f351c7e0d0f151607c`.
- Fixed run: `d2855cb1-987e-45cf-8bfd-413a0b7a9a16`.
- Fixed-overlap run: `be672d66-fa80-40d3-b2d5-eb71f4e903b4`.
- Heading-aware run: `a64fe51b-71d4-4c2b-a6b5-5bf5e370835c`.

All six rows ran successfully against existing completed PostgreSQL/pgvector
snapshots using `text-embedding-3-small`. The complete report is
[retrieval-20261110T083627933914Z.json](../../backend/evaluation-reports/retrieval-20261110T083627933914Z.json).


| Strategy      | Tokens | Overlap | K | EvidenceHit@K | Macro evidence Recall@K |
| ------------- | ------ | ------- | - | ------------- | ----------------------- |
| fixed         | 200    | 0       | 3 | 1.0000        | 0.8611                  |
| fixed         | 200    | 0       | 5 | 1.0000        | 0.9056                  |
| fixed_overlap | 200    | 40      | 3 | 1.0000        | 0.9056                  |
| fixed_overlap | 200    | 40      | 5 | 1.0000        | 0.9056                  |
| heading_aware | 200    | 40      | 3 | 1.0000        | 0.8389                  |
| heading_aware | 200    | 40      | 5 | 1.0000        | 0.9333                  |


### Interpretation

- **EvidenceHit@K:** All six experiments achieved 100%, meaning every eligible test case retrieved at least one expected evidence statement.
- **EvidenceRecall@K:** Increasing K from 3 to 5 improved evidence coverage for `fixed` and `heading_aware`, but not `fixed_overlap`.
- **Provisional Winner:** `heading_aware` at K=5 achieved the highest evidence recall (93.33%) and is the current preferred configuration based on known-evidence coverage.
- **Limitations:** The dataset is small, expected evidence is non-exhaustive, and evidence split across chunks may not be detected.
- **Pending Evaluation:** Human relevance Hit@K and MRR have not been assessed. The provisional winner may change after further evaluation.
- **Diagnostics:** Retrieval results alone cannot determine whether the assistant can handle unanswerable questions or resist prompt injection.
