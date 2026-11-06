# Chunking Strategy Decisions

This document is written solely by Shi Quan. No LLM was involved.

## Knowledge base

Before understanding the chunking strategy, it is best to understand the composition of the knowledge base.

### Structure of a engineering handbook

All 12 handbooks follow the same structure:

* H1 title

  * immediately followed by a H2 heading
* H2 sections

  * paragraphs
  * lists

### Tokens per documents

| Document                       |          Tokens |
| ------------------------------ | --------------: |
| API standards                  |             694 |
| CI/CD and deployment           |             446 |
| Coding standards               |             549 |
| Database standards             |             457 |
| Documentation standards        |             303 |
| Engineering exceptions         |             352 |
| General engineering principles |             421 |
| Incident management            |             402 |
| Observability and logging      |             477 |
| Security standards             |             640 |
| Source control                 |             525 |
| Testing standards              |             449 |
| **Total**                | **5,715** |



## Initial Chunking Strategy

The first plan was to come up with 3 strategies to evaluate. 

The initial strategies were:

* Fixed
  * 500 tokens
* Fixed + overlap
  * 500 tokens
  * 100 overlap
* Heading-aware (500/100)
  * to split a document into smaller pieces based on its headings and sections
  * rather than simply splitting every X tokens
  * still implement a max of 500 tokens + 100 overlap

**At this juncture, embeddings have not been generated.**

## Revised Chunking Strategy (before embedding)

At this point, embedding was set up and ready to execute. But before generating the embeddings and writing into SQL, I decide to take a look at the tokens per document to re-evaluate if 500 tokens is sensible as a starting point.

Looking at the token distribution of the handbooks:

* minimum: 303 tokens
* maximum: 694 tokens
* median: 453 tokens

The chunking strategy moving forward will be adjusted to:

* Fixed
  * 200 tokens
* Fixed + overlap
  * 200 tokens
  * 40 overlap
* Heading-aware (200/40)
  * to split a document into smaller pieces based on its headings and sections
  * rather than simply splitting every X tokens
  * still implement a max of 500 tokens + 100 overlap
