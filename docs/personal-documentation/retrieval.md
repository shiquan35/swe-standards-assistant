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
