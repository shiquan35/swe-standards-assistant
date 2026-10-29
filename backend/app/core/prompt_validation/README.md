# Prompt Validation Tool

A Python tool for validating AI prompts using Google's Gemini AI model. This tool automatically discovers and evaluates all prompts in your repository against security, clarity, and operational feasibility criteria.

## Features

- **Automatic Prompt Discovery**: Scans the entire repository for files matching `*prompt*.yaml` pattern
- **Comprehensive Analysis**: Evaluates 5 key dimensions:
  - Guardrails compliance
  - Injection protections  
  - Protections against user override
  - Clarity
  - Operational feasibility
- **AI-Powered Validation**: Uses Google Gemini AI for intelligent prompt assessment
- **Pydantic Schema Validation**: Enforces structured JSON output with comprehensive type checking and validation
- **Structured Reporting**: Generates detailed YAML evaluation reports and JSON performance logs
- **Robust Error Handling**: Graceful handling of malformed responses with detailed validation errors
- **GitHub Actions Ready**: CI/CD integration with proper exit codes (fails on validation failures)
- **Flexible Deployment**: Works with both Vertex AI and direct Google AI integration
- **Scoring System**: Automated pass/fail determination based on weighted scoring (75% threshold)

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Cloud Project (if using Vertex AI) or Google AI API access
- Repository containing prompt files matching `*prompt*.yaml` pattern

### Installation

1. **Install dependencies** (from the `backend/` directory):
   ```bash
   # Install only the prompt-validation group (other optional groups will be removed from the environment)
   uv sync --group prompt-validation

   # Install all optional groups (recommended for full dev setup)
   uv sync --all-groups
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.sample .env
   # Edit .env with your actual values
   ```

3. **Check the validation prompt: (DO NOT MAKE ANY CHANGE)**
   - Take a look at `prompt.yaml`
   - The file should have a `v1:` key containing your validation prompt
   - The prompt includes comprehensive JSON schema requirements and validation guidelines

4. **Configure Google Cloud authentication (for Vertex AI only):**
   ```bash
   # Install Google Cloud SDK
   curl https://sdk.cloud.google.com | bash
   exec -l $SHELL
   
   # Authenticate
   gcloud auth application-default login
   
   # Set project
   gcloud config set project YOUR_PROJECT_ID
   
   # Enable APIs
   gcloud services enable aiplatform.googleapis.com
   ```

### Environment Variables

| Variable          | Description                                 | Required                  | Default Value            |
|-------------------|---------------------------------------------|---------------------------|--------------------------|
| `GCP_PROJECT_ID`  | Your Google Cloud Project ID                | Yes (if using Vertex AI)  | -                        |
| `GCP_LOCATION`    | GCP region (e.g., us-central1)              | Yes (if using Vertex AI)  | -                        |
| `USE_VERTEXAI`    | Use Vertex AI (true) or Google AI (false)   | Yes                       | -                        |
| `GEMINI_MODEL`    | Gemini model name (e.g., gemini-1.5-flash)  | Yes                       | -                        |
| `PROJECT_README`  | Path to project README for industry context | No                        | backend/README.md        |

## Usage

### How It Works

The tool automatically:
1. Scans the repository for all files matching `*prompt*.yaml` pattern
2. Extracts project industry context from the README file (2nd line)
3. Validates each prompt version against the configured validation criteria
4. **Validates AI responses using Pydantic schema** to ensure structured JSON output
5. **Handles malformed responses gracefully** with detailed error reporting
6. Generates comprehensive reports with pass/fail determination
7. Returns appropriate exit codes for CI/CD integration

### Local Development

```bash
# Run validation on all discovered prompts (from the prompt_validation/ directory)
uv run python script.py
```

### Expected Output

The tool will:
- Print discovery and validation progress to console
- Generate `validation_results/validation_feedback.yaml` with detailed evaluations
- Generate timestamped JSON performance logs in `validation_results/`
- Return exit code 0 if all validations pass, 1 if any fail

### Validation Scoring

Each dimension is scored as:
- **HIGH**: 2 points
- **MEDIUM**: 1 point  
- **LOW**: 0 points

A prompt passes if it achieves ≥75% of the maximum possible score across all dimensions.

## Structured Output Validation

The tool includes comprehensive **Pydantic schema validation** to ensure reliable JSON output:

### Schema Enforcement
- **Strict Field Validation**: All required fields must be present with correct types
- **Assessment Outcome Validation**: Values restricted to exactly "HIGH", "MEDIUM", or "LOW"
- **Recommendation Pattern Validation**: Enforces `issue_N`/`recommendation_N` structure or empty objects `{}`
- **JSON Escape Validation**: Proper handling of special characters in prompt text

### Validation Models
The tool uses these Pydantic models for structured validation:
- `RecommendationModel`: Validates issue/recommendation field patterns
- `DimensionModel`: Enforces assessment outcomes and recommendation structure
- `EvaluationDimensionsModel`: Validates all 5 required evaluation dimensions
- `ValidationResponseModel`: Complete response schema with field aliases

### Benefits
- **100% Reliable Structure**: Guaranteed JSON output format consistency
- **Runtime Safety**: Schema violations caught immediately with clear error messages
- **Development Efficiency**: Detailed validation feedback for debugging malformed responses
- **CI/CD Ready**: Robust error handling prevents pipeline failures from formatting issues

## GitHub Actions Integration

To enable automated prompt validation when prompt files change:

### **Quick Setup**
1. **Copy the template**: Use `.github/workflows/prompt-validation-workflow.yml` as a starting point
2. **Customize paths**: Update file paths and branch names for your project
3. **Configure authentication**: Choose Workload Identity Federation or GitHub Secrets
4. **Test**: Push a prompt file change to trigger validation

### **Key Configuration Options**

**Trigger on prompt changes only** (recommended):
```yaml
on:
  push:
    branches: [main, develop]
    paths: ['**/prompt*.yaml']
```

**Authentication options**:
- **Option A**: Workload Identity Federation (more secure, no secrets needed)
- **Option B**: GitHub repository secrets (simpler setup)

**Path patterns**:
- `**/prompt*.yaml` - All prompt files
- `backend/**/*prompt*.yaml` - Specific directory only

### **Required Secrets** (if using Option B):
Add to GitHub repository → Settings → Secrets:
- `GCP_PROJECT_ID`: Your Google Cloud Project ID
- `GCP_LOCATION`: GCP region (e.g., `us-central1`)
- `USE_VERTEXAI`: `true` or `false`
- `GEMINI_MODEL`: Model name (e.g., `gemini-2.5-flash`)

## File Structure

```
prompt_validation/
├── script.py                    # Main validation script
├── prompt.yaml                  # Validation criteria configuration  
├── sample_prompt.yaml           # Example prompt file
├── .env.sample                  # Environment variables template
├── validation_results/          # Output folder (auto-created)
│   ├── validation_feedback.yaml    # Detailed evaluation results
│   └── run_log_[timestamp].json   # Performance logs
└── README.md                    # Documentation
```

## Output Files

### validation_feedback.yaml
Contains detailed evaluation results for each prompt (now validated with Pydantic schema):
```yaml
filename:
  version:
    "0_passed": true/false
    "1_prompt_under_review": "original prompt text"
    "2_evaluation_dimensions":
      guardrails_compliance:
        assessment_outcome: "HIGH|MEDIUM|LOW"  # Enforced by schema
        recommendation: {}  # Empty if no issues, or issue_N/recommendation_N pairs
      # ... other dimensions (injection_protections, protections_against_user_override, clarity, operational_feasibility)
    "3_revised_prompt": "improved version"
    "_validation_error": "error details"  # Only present if schema validation failed
```

### run_log_[timestamp].json
Contains performance metrics and usage statistics:
```json
{
  "run_timestamp": "2026-03-26T10:30:45.123456",
  "total_validations": 5,
  "total_latency_seconds": 12.345,
  "total_tokens": 15000,
  "validations": [
    {
      "filename": "prompts/my_prompt.yaml",
      "version": "v1", 
      "validation_passed": true,
      "model": "gemini-1.5-flash",
      "latency_seconds": 2.456,
      "input_tokens": 1200,
      "output_tokens": 800,
      "total_tokens": 2000
    }
  ]
}
```

## Troubleshooting

**No prompts found:**
- Ensure files match `*prompt*.yaml` pattern and contain version keys (`v1:`, `v2:`)

**JSON parsing/validation errors:**
- Pydantic now enforces proper JSON structure with detailed error messages
- Check console output for specific schema validation errors
- Verify model name in environment variables

**Authentication errors:**
- Vertex AI: Run `gcloud auth application-default login`
- Verify project ID, location, and API access
- For GitHub Actions: Check secrets configuration

**Environment issues:**
- Reinstall: `uv sync --group prompt-validation` (from backend/ directory)
- Set `PROJECT_README` path if README not found

## Contributing

1. Ensure proper YAML formatting in `prompt.yaml`
2. Test locally before committing
3. Update this README for any new features
4. Follow the existing code style and error handling patterns