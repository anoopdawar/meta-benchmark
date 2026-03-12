"""
LLM Judge scorer — qualitative code quality assessment.

Reads judge/rubric.md and calibration samples, then queries 3 LLM models
(one per provider: Anthropic, OpenAI, Gemini) to score the submission on
5 qualitative dimensions defined in the rubric. Aggregates scores as mean
across models with std dev tracking.

Each provider's API key must be set for that judge to participate.
Pass dry_run=True to skip API calls for pipeline testing.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Default judge dimensions — used when the rubric doesn't specify them.
# Each harness rubric defines its own dimensions; these are extracted from
# the rubric text at runtime (see _extract_dimensions).
FALLBACK_DIMENSIONS = [
    "separation_of_concerns",
    "abstraction_quality",
    "naming_consistency",
    "test_quality",
    "scope_discipline",
]

# One judge per provider for independent scoring.
DEFAULT_JUDGE_MODELS = [
    ("anthropic", "claude-sonnet-4-6"),
    ("openai", "gpt-5.4"),
    ("gemini", "gemini-2.5-pro"),
]


@dataclass
class DimensionScore:
    dimension: str
    score: float  # 0-100
    reasoning: str
    model_scores: list[float] = field(default_factory=list)
    std_dev: float = 0.0


@dataclass
class JudgeResult:
    dimension_scores: dict[str, DimensionScore]
    aggregate_score: float  # 0-100 (mean across dimensions)
    models_used: list[str]
    calibration_anchored: bool
    notes: str = ""


def run_judge(
    submission_path: Path,
    harness_path: Path,
    judge_models: list[tuple[str, str]] | None = None,
    dry_run: bool = False,
) -> JudgeResult:
    """
    Run the LLM judge against the submission.

    Parameters:
        submission_path: Path to the submission directory
        harness_path: Path to the harness directory (for rubric + calibration)
        judge_models: List of (provider, model) tuples. Default: one per provider.
        dry_run: If True, return placeholder scores without calling any LLMs.
    """
    submission_path = Path(submission_path)
    harness_path = Path(harness_path)
    judge_models = judge_models or DEFAULT_JUDGE_MODELS

    rubric_path = harness_path / "judge" / "rubric.md"
    calibration_path = harness_path / "judge" / "calibration"
    harness_name = harness_path.name

    rubric = rubric_path.read_text(encoding="utf-8") if rubric_path.exists() else ""
    dimensions = _extract_dimensions(rubric)
    calibration = _load_calibration(calibration_path)
    code_context = _build_code_context(submission_path / "workspace")

    model_labels = [m[1] for m in judge_models]

    if dry_run:
        return _dry_run_result(model_labels, dimensions)

    # Filter to models whose provider API key is available
    available_models = [(p, m) for p, m in judge_models if _provider_available(p)]
    if not available_models:
        return _dry_run_result(model_labels, dimensions)

    # Run judge for each available model
    all_scores: dict[str, list[float]] = {dim: [] for dim in dimensions}
    all_reasonings: dict[str, list[str]] = {dim: [] for dim in dimensions}

    for provider, model in available_models:
        model_scores = _call_judge_model(
            provider=provider,
            model=model,
            rubric=rubric,
            calibration=calibration,
            code_context=code_context,
            harness_name=harness_name,
            dimensions=dimensions,
        )
        for dim in dimensions:
            all_scores[dim].append(model_scores.get(dim, {}).get("score", 0.0))
            all_reasonings[dim].append(model_scores.get(dim, {}).get("reasoning", ""))

    # Aggregate: mean across models, with std dev
    dimension_scores: dict[str, DimensionScore] = {}
    for dim in dimensions:
        scores = all_scores[dim]
        mean_score = statistics.mean(scores) if scores else 0.0
        std = statistics.stdev(scores) if len(scores) > 1 else 0.0
        # Pick the reasoning from the median-scoring model
        best_idx = min(range(len(scores)), key=lambda i: abs(scores[i] - mean_score))
        reasoning = all_reasonings[dim][best_idx] if all_reasonings[dim] else ""

        dimension_scores[dim] = DimensionScore(
            dimension=dim,
            score=round(mean_score, 1),
            reasoning=reasoning,
            model_scores=scores,
            std_dev=round(std, 2),
        )

    aggregate = statistics.mean(d.score for d in dimension_scores.values())

    used = [m for _, m in available_models]
    return JudgeResult(
        dimension_scores=dimension_scores,
        aggregate_score=round(aggregate, 2),
        models_used=used,
        calibration_anchored=bool(calibration),
        notes=f"LLM judge score (models: {', '.join(used)})",
    )


def _extract_dimensions(rubric: str) -> list[str]:
    """
    Extract dimension names from rubric markdown.

    Looks for '## Dimension N: <Name>' headings and converts to snake_case keys.
    Falls back to FALLBACK_DIMENSIONS if none found.
    """
    pattern = r"##\s+Dimension\s+\d+:\s+(.+)"
    matches = re.findall(pattern, rubric)
    if not matches:
        return FALLBACK_DIMENSIONS

    dimensions = []
    for name in matches:
        # "Plumbing vs. Porcelain Separation" -> "plumbing_vs_porcelain_separation"
        key = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip().lower()
        key = re.sub(r"\s+", "_", key)
        dimensions.append(key)
    return dimensions


def _dry_run_result(model_labels: list[str], dimensions: list[str]) -> JudgeResult:
    """Return placeholder scores for dry runs and testing."""
    dimension_scores = {
        dim: DimensionScore(
            dimension=dim,
            score=0.0,
            reasoning="[dry_run: LLM not called]",
            model_scores=[0.0] * len(model_labels),
        )
        for dim in dimensions
    }
    return JudgeResult(
        dimension_scores=dimension_scores,
        aggregate_score=0.0,
        models_used=model_labels,
        calibration_anchored=False,
        notes="dry_run=True: no LLM calls made. Run with dry_run=False for real scoring.",
    )


def _provider_available(provider: str) -> bool:
    """Check if the given provider's API key is set."""
    import os
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_META_BENCHMARK_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.environ.get("OPENAI_META_BENCHMARK_KEY") or os.environ.get("OPENAI_API_KEY"))
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_META_BENCHMARK_KEY") or os.environ.get("GEMINI_API_KEY"))
    return False


def _load_calibration(calibration_path: Path) -> dict[str, Any]:
    """Load calibration scores from calibration/scores.json."""
    scores_file = calibration_path / "scores.json"
    if not scores_file.exists():
        return {}
    try:
        return json.loads(scores_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _build_code_context(workspace: Path) -> str:
    """
    Build a code context string from the agent's implementation.
    Includes key source files (up to ~10,000 tokens), plus test files
    so the judge can score test_quality.
    """
    if not workspace.exists():
        return "[workspace not found]"

    parts: list[str] = []
    total_chars = 0
    max_chars = 40_000  # ~10k tokens

    def _is_source(p: Path) -> bool:
        return "mutants" not in p.parts and "test" not in p.name.lower()

    def _is_test(p: Path) -> bool:
        return "mutants" not in p.parts and "test" in p.name.lower()

    src_files = sorted(
        [p for p in workspace.rglob("*.py") if _is_source(p)],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    test_files = sorted(
        [p for p in workspace.rglob("*.py") if _is_test(p)],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )

    src_budget = int(max_chars * 0.70)
    test_budget = max_chars - src_budget

    for f in src_files[:10]:
        if total_chars >= src_budget:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            relative = f.relative_to(workspace)
            excerpt = content[:src_budget - total_chars]
            parts.append(f"=== {relative} ===\n{excerpt}")
            total_chars += len(excerpt)
        except OSError:
            continue

    test_chars = 0
    for f in test_files[:10]:
        if test_chars >= test_budget:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            relative = f.relative_to(workspace)
            excerpt = content[:test_budget - test_chars]
            parts.append(f"=== {relative} (tests) ===\n{excerpt}")
            test_chars += len(excerpt)
        except OSError:
            continue

    return "\n\n".join(parts) if parts else "[no Python source files found in workspace]"


def _call_judge_model(
    provider: str,
    model: str,
    rubric: str,
    calibration: dict[str, Any],
    code_context: str,
    harness_name: str,
    dimensions: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Call a judge LLM model and return per-dimension scores.

    Routes to the correct provider SDK based on the provider parameter.
    Returns dict: {dimension_name: {"score": float, "reasoning": str}}
    """
    prompt = _build_judge_prompt(rubric, calibration, code_context, harness_name, dimensions)

    if provider == "anthropic":
        return _call_anthropic(model, prompt, dimensions)
    elif provider == "openai":
        return _call_openai(model, prompt, dimensions)
    elif provider == "gemini":
        return _call_gemini(model, prompt, dimensions)

    return {dim: {"score": 0.0, "reasoning": f"Unknown provider: {provider}"} for dim in dimensions}


def _call_anthropic(model: str, prompt: str, dimensions: list[str]) -> dict[str, dict[str, Any]]:
    """Call Anthropic API."""
    try:
        import os
        import anthropic
        api_key = os.environ.get("ANTHROPIC_META_BENCHMARK_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_judge_response(message.content[0].text, dimensions)
    except Exception:
        return {dim: {"score": 0.0, "reasoning": "Anthropic API call failed"} for dim in dimensions}


def _call_openai(model: str, prompt: str, dimensions: list[str]) -> dict[str, dict[str, Any]]:
    """Call OpenAI API."""
    try:
        import os
        import openai
        api_key = os.environ.get("OPENAI_META_BENCHMARK_KEY") or os.environ.get("OPENAI_API_KEY")
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_judge_response(response.choices[0].message.content, dimensions)
    except Exception:
        return {dim: {"score": 0.0, "reasoning": "OpenAI API call failed"} for dim in dimensions}


def _call_gemini(model: str, prompt: str, dimensions: list[str]) -> dict[str, dict[str, Any]]:
    """Call Gemini API."""
    try:
        import os
        from google import genai
        api_key = os.environ.get("GEMINI_META_BENCHMARK_KEY") or os.environ.get("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(max_output_tokens=2000),
        )
        return _parse_judge_response(response.text, dimensions)
    except Exception:
        return {dim: {"score": 0.0, "reasoning": "Gemini API call failed"} for dim in dimensions}


def _build_judge_prompt(
    rubric: str,
    calibration: dict,
    code_context: str,
    harness_name: str,
    dimensions: list[str],
) -> str:
    """Build the judge prompt with rubric, calibration anchors, and code."""
    cal_examples = ""
    for sample in calibration.get("samples", []):
        cal_examples += f"\nExample '{sample['id']}' ({sample['label']}):\n"
        for dim, data in sample.get("human_scores", {}).items():
            cal_examples += f"  {dim}: {data['score']}/100 — {data['reasoning']}\n"

    dim_format = ""
    for dim in dimensions:
        dim_format += f'  "{dim}": {{"score": <0-100>, "reasoning": "<1-2 sentences>"}},\n'

    return f"""You are an expert code quality judge evaluating a {harness_name} implementation.

## Scoring Rubric

{rubric}

## Calibration Examples (ground truth — anchor your scores to these)

{cal_examples if cal_examples else "No calibration examples available."}

## Implementation to Score

{code_context}

## Task

Score this implementation on each dimension defined in the rubric above.
Respond with ONLY a JSON object in this exact format:

{{
{dim_format}}}"""


def _parse_judge_response(response: str, dimensions: list[str]) -> dict[str, dict[str, Any]]:
    """Parse the judge's JSON response, matching dimension keys flexibly."""
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return {dim: {"score": 0.0, "reasoning": "Parse error"} for dim in dimensions}
    try:
        data = json.loads(match.group())

        # Build a lookup from normalized keys to original keys in the response
        response_keys = {}
        for key in data:
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            response_keys[normalized] = key

        result = {}
        for dim in dimensions:
            normalized_dim = re.sub(r"[^a-z0-9]", "", dim.lower())
            # Try exact match first, then normalized match
            if dim in data:
                entry = data[dim]
            elif normalized_dim in response_keys:
                entry = data[response_keys[normalized_dim]]
            else:
                entry = {"score": 0.0, "reasoning": "Dimension not found in response"}
            result[dim] = {
                "score": float(entry.get("score", 0)),
                "reasoning": str(entry.get("reasoning", "")),
            }
        return result
    except (json.JSONDecodeError, TypeError, ValueError):
        return {dim: {"score": 0.0, "reasoning": "Parse error"} for dim in dimensions}
