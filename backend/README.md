# Project Details

Industry - Healthcare

# FastAPI Backend

A modern FastAPI backend application with SQLModel, structured logging, and comprehensive testing setup.

## Features

- 🚀 **FastAPI** - Modern, fast web framework for building APIs
- 🗄️ **SQLModel** - SQL databases in Python, designed by the creator of FastAPI
- 📝 **Loguru** - Structured logging with rich formatting
- 📄 **Pagination** - Built-in pagination support with fastapi-pagination
- 🛡️ **Security** - Comprehensive security middleware with IP filtering, rate limiting, and CORS
- 🧪 **Testing** - Comprehensive test suite with pytest and coverage
- 🔧 **Code Quality** - Linting and formatting with Ruff
- 📦 **UV** - Ultra-fast Python package manager and project manager

## Project Structure

```
backend/
├── app/
│   ├── core/           # Core functionality (database, logging, environment, security)
│   ├── middlewares/    # Custom middleware
│   ├── models/         # Pydantic/SQLModel models
│   ├── routers/        # API route definitions
│   ├── services/       # Business logic layer
│   └── main.py         # FastAPI application entry point
├── alembic/            # Database migration files
│   ├── versions/       # Generated migration scripts
│   ├── env.py          # Alembic environment configuration
│   ├── script.py.mako  # Migration template
│   └── README          # Alembic documentation
├── tests/              # Test suite
│   ├── core/           # Tests for core functionality
│   ├── routers/        # Tests for API routes
│   ├── conftest.py     # Pytest configuration and fixtures
│   └── test_main.py    # Main application tests
├── tests/              # Save all logs here
├── alembic.ini         # Alembic configuration file
├── pyproject.toml      # Project configuration and dependencies
├── .env                # Environment variables (create from .env.example)
└── README.md           # This file
```

## Requirements

- Python 3.13+
- UV package manager

## Quick Start

### 1. Install UV

If you don't have UV installed, install it first:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clone and Setup

```bash
git clone <repository-url>
cd backend
```

### 3. Install Dependencies

UV will automatically create a virtual environment and install dependencies:

```bash
uv sync
```

### 4. Configure Environment

Create a `.env` file in the backend directory:

```bash
# Create environment file
cat > .env << EOF
DB_FULL_CONNECTION_STRING=sqlite:///./database.db
ENVIRONMENT=development
EOF
```

### 5. Initialize Database

Set up the database with initial migrations:

```bash
# Create initial migration (if none exists)
uv run alembic revision --autogenerate -m "Initial migration"

# Apply migrations to create tables
uv run alembic upgrade head
```

### 6. Run the Development Server

```bash
uv run task dev
```

The API will be available at:

- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/healthcheck
- **Alternative Docs**: http://localhost:8000/redoc

## Development Commands

The project uses `taskipy` for task management. All commands should be run with `uv run`:

### Start Development Server

```bash
uv run task dev
```

Starts the FastAPI development server with auto-reload.

### Code Formatting and Linting

```bash
uv run task format
```

Runs Ruff to check and fix code style issues, then formats the code.

### Run Tests

```bash
uv run task test
```

Runs the test suite with coverage reporting. Coverage reports are generated in `htmlcov/`.

### Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "Description of changes"

# Apply migrations
uv run alembic upgrade head

# Check migration status
uv run alembic current
```

### Manual Commands

You can also run commands directly:

```bash
# Run the app directly
uv run fastapi dev

# Run tests with specific options
uv run pytest -v

# Run linting only
uv run ruff check

# Format code only
uv run ruff format .

# Generate migration without auto-detection
uv run alembic revision -m "Manual migration"

# Downgrade database one revision
uv run alembic downgrade -1
```

### Search the Engineering Handbook

Run from the backend directory:

```bash
uv run python -m app.functions.search_handbook \
   --query "What are the requirements for approving a pull request?" \
   --strategy heading_aware \
   --top-k 5
```

The command calls `retrieve_chunks()` against the latest completed ingestion run
for the selected strategy. It requires a migrated PostgreSQL database with pgvector,
`DB_FULL_CONNECTION_STRING`, and `OPENAI_API_KEY` for query embeddings. Create a
completed snapshot with the ingestion CLI before searching.

`--query` and `--strategy` are required. Strategies are `fixed`, `fixed_overlap`,
and `heading_aware`; `--top-k` defaults to 5 and accepts values from 1 to 100.

Output includes the query, strategy, requested limit, and each chunk's rank,
four-decimal cosine similarity, document title, heading path(s), stored source
path, line range(s), and full content. Multiple heading paths use `;` separators
and multiple line ranges use commas; absent metadata displays `(none)`.
No results prints `No matching chunks found.` and succeeds. Runtime failures
print a safe message to stderr and exit with status 1; invalid arguments exit
with status 2. This retrieves excerpts only; it does not generate an answer.

### Evaluate Handbook Retrieval

Run the module `app.functions.evaluate_retrieval` from the backend directory with
`uv run python -m app.functions.evaluate_retrieval`. Its `--help` requires no
database or provider configuration. There is no taskipy alias.

The default dataset is [tests/rag/retrieval_cases.json](tests/rag/retrieval_cases.json).
Defaults compare all three strategies at 200 tokens, overlap 0 for `fixed` and
40 otherwise, at top-K 3 and 5 (six report experiments). Repeating `--strategy`,
`--max-tokens`, `--overlap-tokens`, or `--top-k` forms a deduplicated Cartesian
grid; fixed overlap always remains zero. For example, append
`--max-tokens 200 --max-tokens 400 --top-k 3 --top-k 5` to compare both sizes.
Top-K must be 1–100, and non-fixed overlap must be smaller than every selected size.

Requires a migrated PostgreSQL/pgvector database, `DB_FULL_CONNECTION_STRING`,
`OPENAI_API_KEY`, and completed ingestion snapshots for every exact configuration
using `text-embedding-3-small`. No ingestion is performed automatically.
Each configuration must have exactly one compatible completed run; resolve
ambiguity with repeated `--run-id STRATEGY:MAX:OVERLAP=UUID` overrides.
All selected runs must contain the same complete path/source-hash mapping and
match the current local handbook. This source-only identity is distinct from
each strategy-dependent full snapshot fingerprint. All preflight checks finish
before question embedding. A missing, ambiguous, or stale run fails the invocation.

Query vectors are cached only for the invocation by model and exact effective
input (outer whitespace trimmed, case/internal whitespace preserved). Each
case/run is retrieved once at maximum K; lower cutoffs slice that ranking.

The console reports **incomplete-ground-truth evidence coverage**, not overall
relevance. JSON includes one experiment per cutoff, per-case ranked full chunks,
source line spans, evidence statements/all matching ranks, source diagnostics,
run fingerprints, dataset SHA-256, configuration and explicit metric denominators.
Human relevance is pending (`relevance: null`); Hit@K/MRR require manual judgments.
Unanswerable and injection cases are separate retrieval diagnostics, not tests of
abstention or instruction resistance. No strategy winner is inferred.

Reports default to UTC-timestamped JSON under the backend evaluation-reports
directory. `--dataset` selects another validated dataset; `--output` sets a report
path. Existing paths require `--force`. Publication is atomic; failures leave no
partial report. Reports contain full handbook text: review them before sharing.
Failures print safe reason codes to stderr (status 1); argparse errors use status 2.
Offline tests can be run with `uv run pytest tests/evaluation --confcutdir=tests/evaluation`.

### Answer a Handbook Question (Single-Turn RAG)

From the backend directory, invoke `uv run python -m app.functions.answer_handbook "What are the requirements for approving a pull request?"`.
Append `--json` for a single typed JSON response instead of human output.
`--help` and argument validation do not import application settings, the database,
or the generation provider. One nonblank positional question is required; outer
whitespace is trimmed. There is no HTTP endpoint, conversation history, or answer
persistence.

Prerequisites: operator-migrated PostgreSQL with pgvector, a configured
`DB_FULL_CONNECTION_STRING`, `OPENAI_API_KEY`, and a completed `heading_aware`
handbook ingestion snapshot using `text-embedding-3-small`. The newest completed
run is selected with no fallback to an older run if its embedding model is
incompatible. Retrieval uses `top_k=5`. Missing snapshots and incompatible runs
are operational errors; successful empty retrieval abstains without generation.
Nonempty evidence triggers at most one OpenAI Responses Structured Outputs
generation request, with automatic generation retries disabled even for injected
clients. Query embedding is a separate request with existing embedding behavior.

The user-selected defaults are:

| Setting | Default | Meaning |
|---|---|---|
| `OPENAI_CHAT_MODEL` | `gpt-6-luna` | Generation model; model/account compatibility is live unverified |
| `RAG_MAX_INPUT_TOKENS` | `32000` | Local estimated input budget |
| `RAG_MAX_OUTPUT_TOKENS` | `4096` | Provider output allowance |
| `RAG_TOKEN_SAFETY_MARGIN` | `.20` | Multiply the input estimate by 1.2 |
| `RAG_MODEL_CONTEXT_WINDOW` | `1050000` | Operator-configured context-window assumption, not verified model capability |

See [env.example](env.example). **Set `OPENAI_CHAT_MODEL=gpt-6-luna` yourself in
your local ignored settings if an older value is present.** Implementation and
offline validation do not read or edit that local file, check account access, or
make paid requests. Live model/account access and Responses/Structured Outputs
compatibility remain unverified until an operator opts into a live check; they
are not implementation gates.

Token accounting uses `tiktoken.encoding_for_model()` when known. By explicit
user override, an unknown model mapping falls back to `o200k_base` for
**unverified estimation**, not a verified tokenizer mapping. Complete logical
JSON request serialization is counted, including model/instructions, escaped
question and evidence, chunk IDs, titles/paths/headings/spans, delimiters,
Structured Outputs schema and format flags, and other request fields. With the
default settings the estimate is
`ceil((serialized_tokens + 256) * 1.2)`: 256 tokens reserve message/SDK framing,
then the 20% margin applies to the entire sum. The estimate must fit the input
budget and, with the output allowance, the configured context window. Include
only a contiguous ranked prefix; stop at the first non-fitting chunk. Do not
truncate evidence or skip to a smaller lower-ranked chunk. Prompt-only or
first-chunk overflow fails before generation.

**Estimates are not guaranteed provider limits.** Real tokenizer/framing behavior
can differ, especially for an unknown model. Provider context-limit rejection
is an operational `provider_context_limit` error, not an abstention. Direct
service calls emit metadata-only `rag_context_prepared` logs (encoding, fallback,
serialized/estimated tokens, included/retrieved IDs and margin) and, when usage
is returned, `rag_token_usage` logs comparing actual input/output tokens with
estimated input (`estimate_error_tokens`, `estimate_exceeded`, and
`actual_input_limit_exceeded`). No question, evidence, completion, or answer text
is logged. The CLI suppresses application diagnostic logs during its invocation
to keep stdout and mode-matched stderr clean; direct function callers retain
metadata logging.

Response content statuses all succeed with exit **0**:

- `answered`: cited claims cover the clear request.
- `partial`: cited claims plus explicit `unanswered_parts`.
- `clarification_needed`: one `clarifying_question`, optionally cited claims and
   unanswered parts; ambiguity takes precedence over partial.
- `abstained`: no claims/citations and a meaningful evidence-only `reason`.

Human output composes claims with inline numbered references and deduplicated
sources containing title, path, heading paths, and line spans; unavailable
metadata displays `(none)`. It also shows reason, unanswered parts, clarifying
question when present, and ingestion run ID. JSON is the `RagResponse` contract:
`status`, `claims` (`text`, `citation_ids`), `citations` (`chunk_id`, nullable
`title`/`file_path`, `heading_paths`, `source_spans`), `ingestion_run_id`, nullable
`clarifying_question`/`reason`, and `unanswered_parts`. No free-form answer field
is generated. The application owns provenance and validates that the final
citations exactly equal the claims' referenced included chunks. Citation support
and atomicity are model-proposed, not independently verified entailment.

Operational failures exit **1**; invalid arguments/blank questions exit **2**.
Errors go only to stderr, human-readable by default or a single JSON object
`{"error":{"reason_code":"…","message":"…"}}` with `--json`. Unknown exceptions
are sanitized to `rag_failed`; rejected arguments, provider/DB details, secrets,
and question text are never echoed. Typical operational codes include
`missing_snapshot`, `run_not_searchable`, `missing_api_key`, `database_error`,
`embedding_failed`, `configuration_failed`, `context_budget_exceeded`,
`provider_context_limit`, `provider_failed`, `model_refusal`, `incomplete_output`,
`invalid_model_output`, and `invalid_citation_source`. These are not content
abstentions.

#### Offline CLI tests and opt-in live smoke

Run `uv run pytest tests/rag/test_answer_handbook.py tests/rag/test_live.py --confcutdir=tests/rag -q`
with `RUN_LIVE_RAG_TEST` unset. CLI tests use fakes and import barriers without DB,
settings-file reads, or OpenAI calls; the live smoke defaults to skipped. The
`--confcutdir` boundary avoids parent application fixtures during discovery.

Only an operator choosing to incur real embedding/generation charges should set
`RUN_LIVE_RAG_TEST=1` and invoke `uv run pytest tests/rag/test_live.py --confcutdir=tests/rag -q`.
The smoke calls `answer_question()` with a session from the application engine
and a real OpenAI client; it does not ingest, migrate, or truncate data. It
requires a populated compatible snapshot and checks a structured, cited outcome
for a known handbook question so empty retrieval cannot masquerade as generation
compatibility. An opted-in failure is not silently skipped. This is a smoke test,
not a quality benchmark or proof of prompt-injection resistance. Do not auto-run
paid tests or publish failure output containing interaction data.

## API Endpoints

### Health Check

- `GET /healthcheck` - Application health status

### Sample Resources

All sample endpoints are prefixed with `/api/samples`:

- `GET /api/samples/` - List all samples (paginated)
- `GET /api/samples/{sample_id}` - Get a specific sample
- `POST /api/samples/` - Create a new sample
- `PATCH /api/samples/{sample_id}` - Update a sample
- `DELETE /api/samples/{sample_id}` - Delete a sample

## Configuration

### Environment Variables

The application uses Pydantic Settings for configuration management through the `app/core/env.py` module. Create a `.env` file in the backend directory for environment-specific configuration:

```env
# Database configuration (required)
DB_FULL_CONNECTION_STRING=sqlite:///./database.db

# Environment configuration
ENVIRONMENT=development
```

#### Required Environment Variables

- `DB_FULL_CONNECTION_STRING`: Complete database connection string (e.g., `sqlite:///./database.db`, `postgresql://user:password@localhost/dbname`)
- `ENVIRONMENT`: Application environment (e.g., `development`, `staging`, `production`). Controls environment-specific settings and behaviors.

### Using Environment Configuration in Code

The project uses a centralized configuration system through `app/core/env.py`:

```python
from app.core.env import env

# Access environment variables
database_url = env.DB_FULL_CONNECTION_STRING
environment = env.ENVIRONMENT
```

The `Env` class is built on Pydantic Settings with the following features:

- Automatic `.env` file loading
- Type validation and coercion
- Default values for optional settings
- Environment variable override support

### Project Configuration

The project configuration is managed in `pyproject.toml`:

- **Dependencies**: Core and development dependencies
- **Ruff**: Code linting and formatting rules
- **Pytest**: Test configuration
- **Taskipy**: Task definitions

## Testing

The project includes a comprehensive test suite:

```bash
# Run all tests
uv run task test

# Run with verbose output
uv run pytest -v

# Run with coverage report
uv run pytest --cov --cov-report=html
```

Test coverage reports are generated in the `htmlcov/` directory.

### Handbook ingestion and stale-run recovery

From the backend directory, run `uv run python -m app.functions.ingest_handbook --strategy heading_aware --max-tokens 200 --overlap-tokens 40`.
Strategies are `fixed`, `fixed_overlap`, and `heading_aware`; `--max-tokens` defaults
to 200, and `--overlap-tokens` defaults to 0 for `fixed`, 40 otherwise. The corpus
is the fixed engineering-handbook directory under knowledge_base. Use a migrated
PostgreSQL database with pgvector via `DB_FULL_CONNECTION_STRING`. The embedding
model is fixed to `text-embedding-3-small` (1,536 dimensions); `OPENAI_API_KEY` is
needed only for uncached embedding requests. Exact completed snapshots are no-ops;
changed snapshots can reuse vectors from completed runs.

A matching running run is refused. After confirming that its worker should be
revoked, use `uv run python -m app.functions.recover_ingestion_run RUN_UUID --confirm`.
Recovery locks the run, marks it failed, and clears its execution token; it does
not ingest. Invoke normal ingestion again to retry with a fresh owner token.

### Destructive PostgreSQL ingestion integration tests

**Warning: use a dedicated disposable database only. Every test truncates all rows
in public.knowledge_chunks, public.ingestion_run_documents,
public.knowledge_documents, and public.ingestion_runs before and after the test.**
Never point this suite at development, staging, production, or any shared database.
There is deliberately no `TRUNCATE CASCADE`; unrelated tables are not cleanup targets.
Stop other users/workers first. Do not run these tests with xdist: an advisory lock
rejects overlapping suite instances against the same database, not arbitrary clients.

The operator must provision PostgreSQL/pgvector and apply reviewed Alembic migrations
**before** running the suite. Fixtures never run migrations, import Alembic's
environment, create tables, or fall back to the application database URL. They read
the single local head using `ScriptDirectory`, compare public.alembic_version,
and inspect actual column types/nullability, keys, checks, and delete cascades
before permitting cleanup. A head stamp alone is insufficient: missing model
checks (including fingerprint length and running-token ownership) fail validation
and require an operator-authored/applied migration.

Set `TEST_DATABASE_URL` explicitly to the disposable PostgreSQL database using
the PostgreSQL/psycopg2 driver, and separately set
`TEST_DATABASE_ALLOW_DESTRUCTIVE=1` to acknowledge the deletion warning. Supply
credentials securely; do not paste them into logs or use pytest's `--showlocals`.
Without both opt-ins the tests skip before connecting. SQLite, other drivers, and
PostgreSQL maintenance databases are rejected. All sessions use public, bounded
connection/lock/statement timeouts, and the explicit test engine. Pipeline helpers
commit, so rollback-only fixtures or a private test schema would not isolate them.
HTTP/provider calls are blocked; prepared documents and embeddings are synthetic.

Run `uv run pytest --confcutdir=tests/ingestion tests/ingestion/test_ingestion_postgres.py -q`.
The `--confcutdir` option is required to exclude the application/SQLite fixtures in
the parent test configuration. For safe discovery without any opt-ins, use the
same invocation with `--collect-only`; no database or API is contacted.

## Code Quality

The project uses Ruff for linting and formatting:

- **Target Python Version**: 3.13
- **Selected Rules**: pycodestyle, pyflakes, isort, flake8-bugbear, and more
- **Auto-fixing**: Many issues can be automatically fixed

```bash
# Check, fix issues and format
uv run task format
```

## Database Migrations with Alembic

This project uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations. Alembic is integrated with SQLModel and automatically detects model changes.

### Prerequisites

Before using Alembic, ensure your environment is properly configured:

1. Set up your `.env` file with the correct `DB_FULL_CONNECTION_STRING`
2. Ensure all your SQLModel models are imported in `alembic/env.py` (currently imports `app.models.sample`)

### Common Alembic Commands

#### Create a New Migration

After modifying your SQLModel models, generate a new migration:

```bash
# Generate migration with automatic detection of model changes
uv run alembic revision --autogenerate -m "Add new table/column description"

# Generate empty migration file for manual changes
uv run alembic revision -m "Custom migration description"
```

#### Apply Migrations

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Apply migrations up to a specific revision
uv run alembic upgrade <revision_id>

# Downgrade to a specific revision
uv run alembic downgrade <revision_id>

# Downgrade one revision
uv run alembic downgrade -1
```

#### Check Migration Status

```bash
# Show current migration status
uv run alembic current

# Show migration history
uv run alembic history

# Show pending migrations
uv run alembic heads
```

### Alembic Configuration

The Alembic configuration is managed through:

- **`alembic.ini`**: Main configuration file with database URL and logging settings
- **`alembic/env.py`**: Environment setup that integrates with your application's configuration
- **`alembic/versions/`**: Directory containing all migration files

#### Key Configuration Features

1. **Automatic Database URL**: The `alembic/env.py` automatically reads the database URL from your environment configuration (`env.DB_FULL_CONNECTION_STRING`)
2. **Model Auto-discovery**: SQLModel metadata is automatically used for migration generation
3. **Environment Integration**: Uses the same environment setup as your application

### Adding New Models

When you create new SQLModel models:

1. **Import the model** in `alembic/env.py`:

   ```python
   import app.models.sample
   import app.models.your_new_model  # Add this line
   ```
2. **Generate migration**:

   ```bash
   uv run alembic revision --autogenerate -m "Add your_new_model table"
   ```
3. **Review the generated migration** in `alembic/versions/` to ensure it's correct
4. **Apply the migration**:

   ```bash
   uv run alembic upgrade head
   ```

### Migration Best Practices

1. **Always review generated migrations** before applying them
2. **Use descriptive migration messages** that explain the changes
3. **Test migrations** on a copy of production data before deploying
4. **Backup your database** before running migrations in production
5. **Keep migrations small and focused** on a single change when possible

### Example Workflow

```bash
# 1. Modify your SQLModel (e.g., add a new field to Sample model)
# 2. Generate migration
uv run alembic revision --autogenerate -m "Add email field to Sample model"

# 3. Review the generated migration file in alembic/versions/
# 4. Apply the migration
uv run alembic upgrade head

# 5. Verify the changes
uv run alembic current
```

## Logging

The application uses Loguru for structured logging:

- Configured in `app/core/logger.py`
- Supports multiple log levels (DEBUG, INFO, WARNING, ERROR)
- Rich formatting and context binding
- Log files are written to `log.log`

## Middleware

- **ProcessTimeMiddleware**: Adds response time headers to all requests

## Security Configuration

The application includes comprehensive security features through `app/core/security.py`, which configures the Guard security middleware. The security settings are environment-aware and automatically adjust based on the `ENVIRONMENT` variable:

### Security Features

- **IP Management**: Whitelist and blacklist support for IP addresses
- **Geographic Filtering**: Option to block requests from specific countries
- **User-Agent Filtering**: Blocks automated tools, bots, and crawlers
- **Rate Limiting**: Configurable request limits per minute
- **Auto-banning**: Automatic IP banning based on suspicious activity
- **Penetration Detection**: Advanced threat detection ⚠️ **Note: can significantly impact performance**
- **HTTPS Enforcement**: Forces secure connections in production
- **CORS Configuration**: Cross-origin resource sharing with environment-specific settings
- **Security Headers**: Automatic security header injection
- **Cloud Provider Blocking**: Optional blocking of cloud provider traffic

### Environment-Specific Behavior

**Development Environment:**

- Permissive CORS settings (`origins: ["*"]`)
- Security features disabled for easier development
- No IP banning or penetration detection
- HTTP connections allowed

**Production Environment:**

- Strict CORS origins (configured domains only)
- All security features enabled
- HTTPS enforcement
- IP banning and rate limiting active
- Detailed security logging to `logs/security.log`

## Dependencies

### Core Dependencies

- `fastapi[standard]` - Web framework with all standard features
- `sqlmodel` - SQL database integration with SQLAlchemy
- `alembic` - Database migration tool for SQLAlchemy
- `loguru` - Advanced logging
- `fastapi-pagination` - Pagination support
- `ulid-py` - ULID generation for unique IDs
- `pydantic-settings` - Settings management with environment variable support

### Development Dependencies

- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `ruff` - Linting and formatting
- `taskipy` - Task runner

## Contributing

1. Install development dependencies: `uv sync`
2. Make your changes
3. Run tests: `uv run task test`
4. Format code: `uv run task format`
5. Commit your changes
