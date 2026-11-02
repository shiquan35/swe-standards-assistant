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
Defaults:
- performs chunking on `api-standards.md`
  - update DEFAULT_PATH in `chunk_handbook.py` 
- heading-aware strategy
```
uv run python -m app.functions.chunk_handbook
```

500 tokens:
```
uv run python -m app.functions.chunk_handbook --strategy fixed
```

500 tokens + 100 overlap:
```
uv run python -m app.functions.chunk_handbook --strategy fixed_overlap
```

custom tokens and overlap:
```
uv run python -m app.functions.chunk_handbook --strategy fixed_overlap --max-tokens 400 --overlap-tokens 80
```