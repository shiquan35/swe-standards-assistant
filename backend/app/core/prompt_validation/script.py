import os
import yaml
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator
from google import genai

from dotenv import load_dotenv

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_LOCATION")
USE_VERTEXAI = os.getenv("USE_VERTEXAI")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]

project_readme_env = os.getenv("PROJECT_README")
if project_readme_env:
    project_readme_path = Path(project_readme_env)
    PROJECT_README = project_readme_path if project_readme_path.is_absolute() else REPO_ROOT / project_readme_path
else:
    PROJECT_README = REPO_ROOT / "backend" / "README.md"

# Pydantic models for structured output validation
class RecommendationModel(BaseModel):
    """Model for recommendation objects with issue/recommendation pairs"""
    model_config = {"extra": "allow"}  # Allow additional fields for issue_N/recommendation_N patterns
    
    @field_validator('*', mode='before')
    @classmethod
    def validate_recommendation_pattern(cls, v, info):
        """Validate that fields follow issue_N/recommendation_N pattern"""
        field_name = info.field_name
        if field_name and field_name.startswith('issue_'):
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"Issue field '{field_name}' must be a non-empty string")
        elif field_name and field_name.startswith('recommendation_'):
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"Recommendation field '{field_name}' must be a non-empty string")
        return v

class DimensionModel(BaseModel):
    """Model for individual evaluation dimensions"""
    assessment_outcome: str = Field(..., pattern="^(HIGH|MEDIUM|LOW)$")
    recommendation: RecommendationModel = Field(default_factory=lambda: RecommendationModel())
    
class EvaluationDimensionsModel(BaseModel):
    """Model for all evaluation dimensions"""
    guardrails_compliance: DimensionModel
    injection_protections: DimensionModel
    protections_against_user_override: DimensionModel
    clarity: DimensionModel
    operational_feasibility: DimensionModel

class ValidationResponseModel(BaseModel):
    """Complete validation response model"""
    prompt_under_review: str = Field(..., alias="1_prompt_under_review")
    evaluation_dimensions: EvaluationDimensionsModel = Field(..., alias="2_evaluation_dimensions")
    revised_prompt: str = Field(..., alias="3_revised_prompt")
    
    model_config = {"populate_by_name": True}

def init():
    print(f"Initializing GenAI client...")
    print(f"GCP Project: {GCP_PROJECT_ID}")
    print(f"GCP Location: {GCP_LOCATION}")
    print(f"Using Vertex AI: {USE_VERTEXAI}")
    client = genai.Client(vertexai=USE_VERTEXAI, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    return client

def get_validation_prompt():
    with open(SCRIPT_DIR / 'prompt.yaml', 'r') as f:
        prompt_config = yaml.safe_load(f)
    return prompt_config.get("v1")

def get_prompt():
    prompts = {}

    for file_path in REPO_ROOT.glob("**/*prompt*.yaml"):
        if file_path == SCRIPT_DIR / 'prompt.yaml':
            continue
        with open(file_path, 'r') as f:
            prompt_config = yaml.safe_load(f)
            relative_path = str(file_path.relative_to(REPO_ROOT))
            prompts[relative_path] = {}
            for version in prompt_config:
                prompts[relative_path][version] = prompt_config[version]
    
    return prompts

def get_readme():
    with open(PROJECT_README, 'r') as f:
        lines = f.readlines()
    if len(lines) >= 2:
        return lines[1].strip()
    else:
        raise Exception(f"README file {PROJECT_README} does not have enough lines to extract project description.")

def clean_and_validate_json_response(response_text: str) -> Dict[str, Any]:
    """Clean response text and validate against Pydantic schema"""
    # Clean the response text
    text = response_text.strip()
    
    # Remove code block markers
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    
    if text.endswith('```'):
        text = text[:-3]
    
    text = text.strip()
    
    # Parse JSON
    try:
        json_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}. Raw response: {text[:200]}...")
    
    # Validate against Pydantic schema
    try:
        validated_response = ValidationResponseModel(**json_data)
        # Convert back to dict with original field names for compatibility
        return {
            "1_prompt_under_review": validated_response.prompt_under_review,
            "2_evaluation_dimensions": {
                "guardrails_compliance": {
                    "assessment_outcome": validated_response.evaluation_dimensions.guardrails_compliance.assessment_outcome,
                    "recommendation": validated_response.evaluation_dimensions.guardrails_compliance.recommendation.model_dump()
                },
                "injection_protections": {
                    "assessment_outcome": validated_response.evaluation_dimensions.injection_protections.assessment_outcome,
                    "recommendation": validated_response.evaluation_dimensions.injection_protections.recommendation.model_dump()
                },
                "protections_against_user_override": {
                    "assessment_outcome": validated_response.evaluation_dimensions.protections_against_user_override.assessment_outcome,
                    "recommendation": validated_response.evaluation_dimensions.protections_against_user_override.recommendation.model_dump()
                },
                "clarity": {
                    "assessment_outcome": validated_response.evaluation_dimensions.clarity.assessment_outcome,
                    "recommendation": validated_response.evaluation_dimensions.clarity.recommendation.model_dump()
                },
                "operational_feasibility": {
                    "assessment_outcome": validated_response.evaluation_dimensions.operational_feasibility.assessment_outcome,
                    "recommendation": validated_response.evaluation_dimensions.operational_feasibility.recommendation.model_dump()
                }
            },
            "3_revised_prompt": validated_response.revised_prompt
        }
    except ValidationError as e:
        error_details = []
        for error in e.errors():
            loc = ' -> '.join(str(x) for x in error['loc'])
            error_details.append(f"{loc}: {error['msg']}")
        raise ValueError(f"Schema validation failed: {'; '.join(error_details)}. Raw response: {text[:200]}...")

def score_response(response):
    evaluation_dimensions = response["2_evaluation_dimensions"]
    
    score_mapping = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    
    score = 0
    
    for _, dimension_data in evaluation_dimensions.items():
        assessment_outcome = dimension_data.get("assessment_outcome", "")
        score += score_mapping.get(assessment_outcome, 0)

    total_dimensions = len(evaluation_dimensions)
    max_score = total_dimensions * 2
    pass_threshold = max_score * 0.75
    
    if score >= pass_threshold:
        feedback = True
    else:
        feedback = False
    
    return feedback

def main():
    try:
        run_timestamp = datetime.now().isoformat()
        log_entries = []
        validation_results = {}
        any_validation_failed = False
        
        client = init()
        validation_prompt = get_validation_prompt()
        user_prompts = get_prompt()
        project_industry = get_readme()
        
        if not validation_prompt:
            print("ERROR: No validation prompt found in prompt.yaml")
            return 1
            
        if not user_prompts:
            print("ERROR: No prompts found matching *prompt*.yaml pattern")
            return 1
            
        print(f"Using validation instruction ({len(validation_prompt)} characters)")
        print(f"Project Industry: {project_industry}")
        
        total_prompts = sum(len(versions) for versions in user_prompts.values())
        print(f"Found {total_prompts} prompts across {len(user_prompts)} files to validate")
        
        for filename, versions in user_prompts.items():
            validation_results[filename] = {}
            
            for version, user_prompt in versions.items():
                print(f"\nValidating {filename} version {version} ({len(user_prompt)} characters)...")
                
                combined_prompt = validation_prompt.replace("{{project_industry}}", project_industry).replace("{{prompt_to_validate}}", user_prompt)
                
                start_time = time.time()
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=combined_prompt,
                )
                end_time = time.time()
                latency_seconds = end_time - start_time

                try:
                    validation_results[filename][version] = clean_and_validate_json_response(response.text)
                except (ValueError, json.JSONDecodeError) as e:
                    print(f"ERROR: Response validation failed for {filename} version {version}")
                    print(f"Validation error: {e}")
                    print(f"Raw response: {response.text[:300]}...")
                    
                    # Create a fallback response indicating validation failure
                    validation_results[filename][version] = {
                        "1_prompt_under_review": user_prompt[:100] + "...",
                        "2_evaluation_dimensions": {
                            "guardrails_compliance": {"assessment_outcome": "LOW", "recommendation": {"issue_1": "Response validation failed", "recommendation_1": "Manual review required"}},
                            "injection_protections": {"assessment_outcome": "LOW", "recommendation": {"issue_1": "Response validation failed", "recommendation_1": "Manual review required"}},
                            "protections_against_user_override": {"assessment_outcome": "LOW", "recommendation": {"issue_1": "Response validation failed", "recommendation_1": "Manual review required"}},
                            "clarity": {"assessment_outcome": "LOW", "recommendation": {"issue_1": "Response validation failed", "recommendation_1": "Manual review required"}},
                            "operational_feasibility": {"assessment_outcome": "LOW", "recommendation": {"issue_1": "Response validation failed", "recommendation_1": "Manual review required"}}
                        },
                        "3_revised_prompt": user_prompt,
                        "_validation_error": str(e)
                    }

                validation_passed = score_response(validation_results[filename][version])
                validation_results[filename][version]["0_passed"] = validation_passed
                
                if not validation_passed:
                    any_validation_failed = True
                
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) if hasattr(response, 'usage_metadata') else 0
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) if hasattr(response, 'usage_metadata') else 0
                total_tokens = input_tokens + output_tokens
                
                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "filename": filename,
                    "version": version,
                    "validation_passed": validation_results[filename][version]["0_passed"],
                    "model": GEMINI_MODEL,
                    "latency_seconds": round(latency_seconds, 3),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "prompt_length_chars": len(user_prompt),
                    "combined_prompt_length_chars": len(combined_prompt)
                }
                log_entries.append(log_entry)
                
                print(f"{filename} version {version} validation complete")
                print(f"   Latency: {latency_seconds:.3f}s | Tokens: {total_tokens}")

        results_dir = SCRIPT_DIR / 'validation_results'
        os.makedirs(results_dir, exist_ok=True)
        
        validation_output_file = results_dir / 'validation_feedback.yaml'
        with open(validation_output_file, 'w') as f:
            yaml.dump(validation_results, f, default_flow_style=False, allow_unicode=True)
        
        print(f"\nAll validation feedback saved: {os.path.abspath(validation_output_file)}")
        
        log_filename = results_dir / f'run_log_{run_timestamp.replace(":", "-").replace(".", "-")}.json'
        with open(log_filename, 'w') as f:
            json.dump({
                "run_timestamp": run_timestamp,
                "total_validations": len(log_entries),
                "total_latency_seconds": round(sum(entry["latency_seconds"] for entry in log_entries), 3),
                "total_tokens": sum(entry["total_tokens"] for entry in log_entries),
                "validations": log_entries
            }, f, indent=2)
        
        print(f"\n Performance log saved: {os.path.abspath(log_filename)}")
        
        if any_validation_failed:
            print("\nOne or more prompt validations failed")
            return 1
        else:
            print("\nAll prompt validations passed")
            return 0
        
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        error_msg = str(e)
        traceback_info = traceback.format_exc()
        
        print(f"ERROR: Validation failed with {error_type}: {error_msg}")
        print(f"Traceback:")
        print(traceback_info)
        return 1


if __name__ == "__main__":
    exit(main())