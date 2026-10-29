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
