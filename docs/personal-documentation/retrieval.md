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

## Evaluation report template
