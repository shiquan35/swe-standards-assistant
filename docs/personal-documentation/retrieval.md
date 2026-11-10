# Retrieval Evaluation

To assess the following:

* To determine whether the vector search can consistently find the correct information.
* Which chunking strategy performs best?
* How does changing `top_k`, chunk size and overlap affect results?

## Preparation

- test dataset in JSON
- define evaluation metrics

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

## Evaluation Runner

From the backend directory, run the module `app.functions.evaluate_retrieval`.
See [CLI usage and prerequisites](../../backend/README.md#evaluate-handbook-retrieval).
It defaults to the six rows above. Repeated strategy, token, overlap and top-K
options expand a deduplicated Cartesian grid; fixed always has zero overlap.
The evaluator never creates ingestion runs. It requires one exact completed,
model-compatible run per configuration (or explicit run-ID overrides), all with
identical source-only fingerprints matching the current handbook. Full ingestion
fingerprints intentionally differ across configurations and are not compared for
source equivalence.

## Evaluation Metrics

Evidence is matched after whitespace collapse and Unicode casefold. Each entire
statement must appear within one chunk; statements split across chunks do not
match. Normalized duplicate statements count once, even when several chunks match;
all matching ranks remain in the report. Source-basename matches are diagnostics,
not relevance labels.

For a case with $E$ distinct expected statements and $M$ matched statements:

$$\mathrm{EvidenceHit@K}=\mathbf{1}[M>0],\qquad
\mathrm{EvidenceRecall@K}=M/E.$$

Core aggregates are macro averages over cases with `answerable == true`, nonempty
evidence, and category other than `Prompt Injection and Instruction Handling`.
Every aggregate reports its eligible-case denominator; empty groups yield null
metrics with count zero. Unanswerable/injection diagnostics are separate, and
evidence-bearing diagnostic cases may have evidence coverage without entering core
aggregates. No-evidence diagnostic metrics are null, not zero.

These are **incomplete-ground-truth evidence coverage**, not overall relevance.
Human Hit@K and MRR remain unavailable until ranked chunks receive manual relevance
judgments. Useful unlisted evidence is not automatically irrelevant. Retrieval
diagnostics cannot establish abstention behavior or prompt-injection resistance;
manual review is needed before choosing a best strategy.

## Report and Baseline Verification

JSON has metadata and one experiment per strategy/token/overlap/top-K row, each
with full per-case chunks, source spans, all evidence matches, explicit denominators
and pending relevance fields. Retrieve maximum K once per case/run and slice lower
cutoffs; query embedding reuse is invocation-scoped and keyed by exact API input
plus model. Reports are atomic and refuse overwrite without `--force`.

### Baseline results — 2026-11-10

All six rows ran successfully against existing completed PostgreSQL/pgvector
snapshots using `text-embedding-3-small`. The complete report is
[retrieval-20261110T080314986726Z.json](../../backend/evaluation-reports/retrieval-20261110T080314986726Z.json).
Each experiment includes all 24 cases; the core denominator is 15. Seven cases
are unanswerable; three are injection diagnostics (two evidence-bearing), with
one unanswerable injection case appearing in both diagnostic groups.

| Strategy | Tokens | Overlap | K | EvidenceHit@K | Macro evidence Recall@K |
|---|---|---|---|---|---|
| fixed | 200 | 0 | 3 | 1.0000 | 0.8611 |
| fixed | 200 | 0 | 5 | 1.0000 | 0.9056 |
| fixed_overlap | 200 | 40 | 3 | 1.0000 | 0.9056 |
| fixed_overlap | 200 | 40 | 5 | 1.0000 | 0.9056 |
| heading_aware | 200 | 40 | 3 | 1.0000 | 0.8389 |
| heading_aware | 200 | 40 | 5 | 1.0000 | 0.9333 |

Provenance:
- Dataset SHA-256: `5460bc60b6f8e3108d79506b51855f8ccb28633f03ce93a50d672c1ab3b9b4aa`.
- Shared source-only SHA-256: `10995f5f1a73558e26b99e6733b2bf921c8ea73e0aa556f351c7e0d0f151607c`.
- Fixed run: `d2855cb1-987e-45cf-8bfd-413a0b7a9a16`.
- Fixed-overlap run: `be672d66-fa80-40d3-b2d5-eb71f4e903b4`.
- Heading-aware run: `a64fe51b-71d4-4c2b-a6b5-5bf5e370835c`.

Interpretation: every core case retrieved at least one labeled statement at both
cutoffs, so EvidenceHit does not distinguish these rows. Increasing K improved
known-evidence coverage for fixed and heading-aware, but not fixed-overlap.
Heading-aware at K=5 has the largest measured evidence recall in this run; this
does **not** establish a relevance winner. The sample is small, evidence labels
are incomplete, and whole-statement matching misses evidence split across chunks.
All human relevance judgments and Hit@K/MRR remain pending. No abstention or
instruction-resistance conclusion can be drawn from the diagnostic retrievals.
