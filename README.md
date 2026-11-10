# Developer Standards Assistant

A centralized, conversational interface for accessing engineering knowledge.

To help developers quickly find and understand engineering best practices, development standards, and company-specific guidelines.

## Application Workflow

1. Developer asks a question
2. Question embedding
   * convert question into a vector
3. Vector search
   * Retrieve relevant handbook chunks
4. LLM answer generation
5. Developer receives answer with source citations

## Stack

| Component       | Technology                        |
| --------------- | --------------------------------- |
| Frontend        | NextJS                            |
| Backend         | FastAPI                           |
| Authentication  | Supabase Auth                     |
| Database        | Supabase PostgreSQL               |
| Vector storage  | pgvector                          |
| Embedding model | OpenAI `text-embedding-3-small` |
| LLM             | OpenAI API                        |
| Knowledge base  | Markdown files in repo            |

## Running this app

### Create .env

```
cd backend
```

```
cp -n env.example .env
```

### Run backend

Create .env

```
DB_FULL_CONNECTION_STRING=postgresql://postgres.mpgnugdrpvxlikolonhp:[YOUR-PASSWORD]@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres
ENVIRONMENT=development
LANGTRACE_API_KEY=''
```

Install dependencies (this will create .venv)

```
uv sync
```

Enter virtual environment

```
source .venv/bin/activate
```

Run server

```
uv run task dev
```

### Test markdown parser

Parses `api-standards.md` by default

```
uv run python -m app.functions.parse_handbook
```

```
uv run python -m app.functions.parse_handbook knowledge_base/engineering-handbook/coding-standards.md
```

### Test chunkers

Note:
Shortest document is `engineering-exceptions.md` with 49 lines and 367 tokens.

Defaults:

- performs chunking on `api-standards.md`
  - update DEFAULT_PATH in `chunk_handbook.py`
- heading-aware strategy: 200 tokens + 40 overlap

```
uv run python -m app.functions.chunk_handbook
```

```
uv run python -m app.functions.chunk_handbook --max-tokens 200 --overlap-tokens 40
```

200 tokens, no overlap:

```
uv run python -m app.functions.chunk_handbook --strategy fixed
```

```
uv run python -m app.functions.chunk_handbook --strategy fixed --max-tokens 200 --overlap-tokens 0
```

200 tokens + 40 overlap:

```
uv run python -m app.functions.chunk_handbook --strategy fixed_overlap
```

```
uv run python -m app.functions.chunk_handbook --strategy fixed_overlap --max-tokens 200 --overlap-tokens 40
```

custom tokens and overlap:

```
uv run python -m app.functions.chunk_handbook --strategy fixed_overlap --max-tokens 150 --overlap-tokens 30
```

```
uv run python -m app.functions.chunk_handbook --strategy heading_aware --max-tokens 100 --overlap-tokens 20
```

### Generate embeddings (WRITES INTO SQL)

```
uv run python -m app.functions.ingest_handbook --strategy fixed
```

```
uv run python -m app.functions.ingest_handbook --strategy fixed_overlap
```

```
uv run python -m app.functions.ingest_handbook --strategy heading_aware
```

### Run retrievals

```
uv run python -m app.functions.search_handbook \
  --query "What are the requirements for approving a pull request?" \
  --strategy fixed \
  --top-k 5
```

```
uv run python -m app.functions.search_handbook \
  --query "What are the requirements for approving a pull request?" \
  --strategy fixed_overlap \
  --top-k 5
```

```
uv run python -m app.functions.search_handbook \
  --query "What are the requirements for approving a pull request?" \
  --strategy heading_aware \
  --top-k 5
```

Sample output:
```
(backend) ongshiquan@KY9YHN-C79E6C55 backend % uv run python -m app.functions.search_handbook \
  --query "What are the requirements for approving a pull request?" \
  --strategy fixed \
  --top-k 5
09:51:12 | retrieval_started strategy=fixed top_k=5 run_id=None question_chars=55 model=text-embedding-3-small
09:51:14 | retrieval_run_selected strategy=fixed run_id=d2855cb1-987e-45cf-8bfd-413a0b7a9a16 created_at=2026-11-05 02:38:02.827556+00:00 selection=latest_completed
09:51:15 | retrieval_vector_query operation=exact_cosine_search operator=cosine_distance strategy=fixed run_id=d2855cb1-987e-45cf-8bfd-413a0b7a9a16 top_k=5 embedding_dimensions=1536
09:51:16 | retrieval_vector_query_completed strategy=fixed run_id=d2855cb1-987e-45cf-8bfd-413a0b7a9a16 candidate_count=5 duration_ms=271.28
09:51:16 | retrieval_completed strategy=fixed run_id=d2855cb1-987e-45cf-8bfd-413a0b7a9a16 result_count=5 results=[{'chunk_id': '34d5bb3c-77bf-4a25-81c1-d8e1f5e290ad', 'rank': 1, 'similarity_score': 0.5726784439481161}, {'chunk_id': '9ffb7a09-0819-4485-8401-086369691a2a', 'rank': 2, 'similarity_score': 0.541365017778909}, {'chunk_id': 'f4970a3f-8d6e-4ce0-abd8-347bd577ea76', 'rank': 3, 'similarity_score': 0.42700837710999795}, {'chunk_id': '003fa879-f3c6-4ad0-95f8-58ed87dda470', 'rank': 4, 'similarity_score': 0.42138592392864704}, {'chunk_id': '1b6826e6-57aa-45b6-b0f5-30b57cdc74d4', 'rank': 5, 'similarity_score': 0.35542330010312395}] duration_ms=3191.66
Query: What are the requirements for approving a pull request?
Strategy: fixed
Top-K: 5

Rank: 1
Similarity: 0.5727
Document: Source Control Standards
Heading: Source Control Standards > 4. Commits; Source Control Standards > 5. Pull requests; Source Control Standards > 6. Code review
Source: backend/knowledge_base/engineering-handbook/source-control.md
Lines: 39-39, 41-41, 43-43, 45-48, 49-49, 51-51, 53-53, 55-55, 57-63, 64-64, 66-66, 68-68, 70-70, 72-72, 74-82

Rank: 2
Similarity: 0.5414
Document: Source Control Standards
Heading: Source Control Standards > 6. Code review; Source Control Standards > 7. Merge requirements; Source Control Standards > 8. Emergency changes
Source: backend/knowledge_base/engineering-handbook/source-control.md
Lines: 74-82, 83-83, 85-85, 87-87, 89-89, 91-91, 93-93, 95-95, 97-97

Rank: 3
Similarity: 0.4270
Document: Testing Standards
Heading: Testing Standards > 4. End-to-end tests; Testing Standards > 5. Test coverage; Testing Standards > 6. Pull request testing; Testing Standards > 7. Test data; Testing Standards > 8. Flaky tests
Source: backend/knowledge_base/engineering-handbook/testing-standards.md
Lines: 38-38, 40-40, 42-42, 44-44, 46-46, 48-48, 50-50, 52-52, 54-54, 56-56, 58-58, 60-60, 62-62, 64-64, 66-66

Rank: 4
Similarity: 0.4214
Document: Source Control Standards
Heading: Source Control Standards; Source Control Standards > 1. Repository requirements; Source Control Standards > 2. Default branch; Source Control Standards > 3. Branch naming; Source Control Standards > 4. Commits
Source: backend/knowledge_base/engineering-handbook/source-control.md
Lines: 3-3, 5-5, 7-7, 9-14, 15-15, 17-17, 19-19, 21-21, 23-23, 25-25, 27-27, 29-34, 35-35, 37-37, 39-39

Rank: 5
Similarity: 0.3554
Document: Coding Standards
Heading: Coding Standards; Coding Standards > 1. General requirements; Coding Standards > 2. Naming; Coding Standards > 3. Functions and modules; Coding Standards > 4. Comments
Source: backend/knowledge_base/engineering-handbook/coding-standards.md
Lines: 3-3, 5-5, 7-7, 9-9, 11-11, 13-13, 15-15, 17-17, 19-22, 23-23, 25-25, 27-27, 29-29, 31-31, 33-33
```
### Run Retrieval Evaluation
Run 6 default experiments:
200 tokens with. top-k 3 and 5.
```bash
uv run python -m app.functions.evaluate_retrieval
```

View all options
```bash
uv run python -m app.functions.evaluate_retrieval --help
```

Run a specific configuration
```bash
uv run python -m app.functions.evaluate_retrieval \
  --strategy heading_aware \
  --max-tokens 200 \
  --overlap-tokens 40 \
  --top-k 5 \
  --output evaluation-reports/my-evaluation.json
```