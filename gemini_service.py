"""Gemini AI integration for the Personal Finance Advisor Bot.

Responsibilities:
- read the API key / model name from the environment (or caller config)
- build a prompt containing the Python-calculated financial snapshot
- request a *structured* JSON response using a Pydantic schema
- validate and normalise the response before returning it as a dictionary

The API key is never logged and never returned to the browser.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import List

from pydantic import BaseModel, Field, ValidationError

from config import DEFAULT_GEMINI_MODEL
from finance_service import CATEGORY_LABELS

logger = logging.getLogger(__name__)

VALID_PRIORITIES = {"high", "medium", "low"}


# --------------------------------------------------------------------------
# Failure classification and retry policy
#
# Google's most popular Flash model occasionally answers with a temporary
# 503 ("This model is currently experiencing high demand") - especially on
# the free tier at peak hours. Those spikes are usually short-lived, so:
#
# 1. each model is retried a few times with a small backoff, and
# 2. if it stays busy, the next model from GEMINI_FALLBACK_MODELS is tried
#    before the user ever sees a friendly "try again in a moment" error.
# --------------------------------------------------------------------------

MAX_ATTEMPTS = 3            # 1 initial call + up to 2 retries per model
RETRY_DELAYS = (1.5, 3.0)   # seconds to wait before each retry

TRANSIENT_TOKENS = (
    "503",
    "unavailable",
    "high demand",
    "overloaded",
    "timeout",
    "timed out",
    "deadline",
    "429",
    "quota",
    "rate limit",
    "resource_exhausted",
)

# Key rejected - retrying or switching models cannot help.
AUTH_TOKENS = (
    "api key",
    "api_key",
    "401",
    "403",
    "unauthenticated",
    "permission",
    "forbidden",
)

# The model does not exist / is not usable with this key - try another model.
MODEL_TOKENS = (
    "404",
    "not found",
    "not supported",
    "does not exist",
    "not available",
)


def _sleep(seconds: float) -> None:
    """Wait helper - a module attribute so tests can patch it out."""
    time.sleep(seconds)


def _is_transient_error(exc: Exception) -> bool:
    """True when the failure looks temporary and retrying is worthwhile."""
    message = str(exc).lower()
    return any(token in message for token in TRANSIENT_TOKENS)


def _error_kind(exc: Exception) -> str:
    """Classify an SDK failure to decide what happens next.

    Returns one of:
    - "auth":      the API key was rejected - nothing but a new key helps
    - "model":     this model does not exist / is not usable with this key
    - "transient": temporary (overload, quota, timeout) - retry or switch
    - "other":     unknown permanent failure - fail fast
    """
    message = str(exc).lower()
    if any(token in message for token in AUTH_TOKENS):
        return "auth"
    if any(token in message for token in MODEL_TOKENS):
        return "model"
    if _is_transient_error(exc):
        return "transient"
    return "other"


def parse_fallback_models(value) -> list[str]:
    """Normalise GEMINI_FALLBACK_MODELS into a clean list of model names.

    Accepts the raw comma-separated string from the environment (or any
    iterable) and returns non-empty, de-duplicated names in order.
    """
    if value is None:
        return []
    raw_items = value.split(",") if isinstance(value, str) else list(value)
    seen: set[str] = set()
    models: list[str] = []
    for item in raw_items:
        name = str(item).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            models.append(name)
    return models


# --------------------------------------------------------------------------
# Errors (all carry user-friendly messages; details stay in server logs)
# --------------------------------------------------------------------------

class GeminiError(Exception):
    """Base class for user-friendly Gemini failures."""


class GeminiConfigError(GeminiError):
    """The integration is not configured correctly (missing key / package)."""


class GeminiAPIError(GeminiError):
    """The Gemini API call failed (invalid key, bad request, network...)."""


class GeminiUnavailableError(GeminiError):
    """The Gemini API is temporarily busy/overloaded - worth retrying later."""


class GeminiResponseError(GeminiError):
    """Gemini returned something that could not be validated."""


# --------------------------------------------------------------------------
# Structured output schema (Pydantic models)
# --------------------------------------------------------------------------

class BudgetAllocation(BaseModel):
    category: str = Field(description="Expense category name, matching the snapshot")
    current_amount: float = Field(description="What the user currently spends per month")
    recommended_amount: float = Field(description="Recommended monthly spending")
    reason: str = Field(description="Short, practical reason for the recommendation")


class BudgetPlan(BaseModel):
    summary: str = Field(description="One or two sentences describing the budget approach")
    recommended_allocations: List[BudgetAllocation]


class SpendingAnalysis(BaseModel):
    summary: str
    observations: List[str]
    high_priority_categories: List[str]


class SavingSuggestion(BaseModel):
    suggestion: str
    estimated_monthly_impact: float = Field(
        description="Estimated monthly saving as a plain number in the user's currency"
    )
    priority: str = Field(description="One of: high, medium, low")


class GoalStrategy(BaseModel):
    goal_name: str
    target_amount: float
    monthly_target: float
    strategy: str


class FinancialAdvice(BaseModel):
    """The full structured analysis returned by Gemini."""

    budget_plan: BudgetPlan
    spending_analysis: SpendingAnalysis
    saving_suggestions: List[SavingSuggestion]
    goal_strategy: GoalStrategy
    monthly_summary: str
    key_insights: List[str]
    warnings: List[str]


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the "Personal Finance Advisor Bot", an educational
personal-finance planning assistant built into a Flask web application. You turn
a user's verified financial snapshot into a structured, personalised analysis.

STRICT RULES:
1. Every number in the snapshot was calculated by the application. Treat those
   values as authoritative facts. NEVER recalculate them, NEVER contradict them
   and NEVER invent income, expense or goal figures that are not in the snapshot.
2. When you mention totals (income, total expenses, remaining income, savings
   rate, goal requirement), quote the snapshot values exactly.
3. You do NOT have access to the user's bank accounts, cards, credit history or
   transaction data. Never imply that you do.
4. You are NOT a licensed financial advisor and this is NOT regulated financial
   advice. Present everything as educational, general personal-finance guidance.
5. Do NOT recommend specific financial products, stocks, securities, mutual
   funds, loans, insurance policies or crypto assets. Focus on budgeting,
   spending awareness, saving habits and goal planning.
6. Be practical, specific and encouraging. Tailor every recommendation to the
   user's actual numbers (suggest realistic adjustments, not drastic cuts).
7. Amounts are plain numbers in the user's own currency. Do not add currency
   symbols and do not convert currencies.
8. If the snapshot does not contain enough information for a conclusion, say so
   explicitly instead of guessing.
9. estimated_monthly_impact values must be realistic and, added together, must
   not exceed the user's remaining income.
10. Respond ONLY with JSON matching the provided schema."""


def build_user_prompt(snapshot: dict) -> str:
    """Build the user prompt from the calculated snapshot."""
    # Present expenses with their friendly labels so the advice reads naturally.
    prompt_snapshot = dict(snapshot)
    prompt_snapshot["expenses"] = {
        CATEGORY_LABELS.get(category, category): amount
        for category, amount in snapshot["expenses"].items()
    }

    return (
        "USER FINANCIAL SNAPSHOT FOR THIS MONTH\n"
        "(every number below was calculated and verified by the application - "
        "use these values exactly as given)\n\n"
        f"{json.dumps(prompt_snapshot, indent=2)}\n\n"
        "TASK\n"
        "Produce the structured financial analysis for this user.\n"
        "- budget_plan.recommended_allocations: 5 to 8 items covering their main "
        "expense categories. Use the exact category names from the snapshot. "
        "current_amount must equal the snapshot amount for that category. "
        "recommended_amount must be a realistic adjustment with a short, practical reason.\n"
        "- spending_analysis: describe the spending pattern, compare categories "
        "against each other and against income, and list the 1-3 categories that "
        "most deserve attention in high_priority_categories.\n"
        "- saving_suggestions: 3 to 6 concrete, personalised actions. "
        "estimated_monthly_impact is a plain monthly number and, added together, "
        "must stay within the user's remaining income. priority is high, medium or low.\n"
        "- goal_strategy: use the goal details from the snapshot. If a target "
        "amount and monthly requirement are provided, use those exact numbers and "
        "explain how to reach the goal within the duration. If they are not "
        "provided, set them to 0 and give general guidance for working toward the goal.\n"
        "- monthly_summary: 3-5 sentences summarising the user's financial "
        "position this month in plain language.\n"
        "- key_insights: 3-5 short, specific insights grounded in the numbers above.\n"
        "- warnings: real risks only - negative remaining income, savings rate "
        "below 10%, goal not achievable within the duration, or one category "
        "dominating spending. If nothing is concerning, use an empty list.\n\n"
        "Remember: educational guidance only, no specific financial products, "
        "no claims about bank accounts, and never change or recompute the "
        "supplied figures."
    )


# --------------------------------------------------------------------------
# Client handling
# --------------------------------------------------------------------------

def _get_client(api_key: str | None):
    """Create a Google GenAI client, with clear errors when misconfigured."""
    key = (api_key or os.environ.get("GEMINI_API_KEY", "") or "").strip()
    if not key:
        raise GeminiConfigError(
            "The Gemini API key is missing. Add GEMINI_API_KEY to your .env file "
            "(see .env.example) and restart the app."
        )
    try:
        from google import genai  # imported lazily so the app still boots
    except ImportError as exc:  # pragma: no cover - depends on install state
        raise GeminiConfigError(
            "The google-genai package is not installed. "
            "Run: pip install -r requirements.txt"
        ) from exc
    try:
        return genai.Client(api_key=key)
    except Exception as exc:
        logger.warning("Could not initialise the Gemini client: %s", type(exc).__name__)
        raise GeminiConfigError(
            "The Gemini client could not be initialised. Please check your "
            "GEMINI_API_KEY in the .env file."
        ) from exc


def _friendly_api_error(exc: Exception) -> str:
    """Translate an SDK exception into a safe, user-friendly message."""
    message = str(exc).lower()
    if any(token in message for token in AUTH_TOKENS):
        return (
            "The Gemini API key was rejected. Please double-check GEMINI_API_KEY "
            "in your .env file."
        )
    if any(token in message for token in ("429", "quota", "rate limit", "resource_exhausted")):
        return (
            "Gemini's free-tier quota is exhausted for now. Please wait a little "
            "and try again."
        )
    if any(token in message for token in ("404", "not found", "is not supported")):
        return (
            "The configured Gemini model is unavailable. Check GEMINI_MODEL in "
            "your .env file."
        )
    if any(
        token in message
        for token in (
            "503", "unavailable", "high demand", "overloaded",
            "timeout", "timed out", "deadline",
        )
    ):
        return (
            "Gemini is temporarily unavailable (the model may be very busy "
            "right now). Please try again in a moment."
        )
    return "The Gemini AI service could not be reached. Please try again shortly."


def _extract_advice(response) -> FinancialAdvice:
    """Validate the Gemini response into a FinancialAdvice model."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, FinancialAdvice):
        return parsed

    # Fallback: parse the raw JSON text ourselves.
    try:
        text = (getattr(response, "text", "") or "").strip()
    except Exception:
        text = ""
    if text:
        try:
            return FinancialAdvice.model_validate_json(text)
        except ValidationError as exc:
            logger.warning("Gemini JSON failed schema validation: %s", exc)
            raise GeminiResponseError(
                "The AI returned an unexpected response format. Please try again."
            ) from exc

    logger.warning("Gemini returned an empty or unparsable response")
    raise GeminiResponseError(
        "The AI could not generate an analysis for this input. Please try again."
    )


def _normalise_advice(model: FinancialAdvice) -> dict:
    """Clean up the validated advice into a predictable dictionary."""
    data = model.model_dump()

    for suggestion in data["saving_suggestions"]:
        suggestion["priority"] = str(suggestion["priority"]).strip().lower()
        if suggestion["priority"] not in VALID_PRIORITIES:
            suggestion["priority"] = "medium"
        suggestion["estimated_monthly_impact"] = round(
            max(0.0, float(suggestion["estimated_monthly_impact"])), 2
        )

    for allocation in data["budget_plan"]["recommended_allocations"]:
        allocation["current_amount"] = round(float(allocation["current_amount"]), 2)
        allocation["recommended_amount"] = round(float(allocation["recommended_amount"]), 2)

    strategy = data["goal_strategy"]
    strategy["target_amount"] = round(max(0.0, float(strategy["target_amount"])), 2)
    strategy["monthly_target"] = round(max(0.0, float(strategy["monthly_target"])), 2)

    # Trim string lists so the UI never renders stray whitespace.
    for section, field in (
        ("spending_analysis", "observations"),
        ("spending_analysis", "high_priority_categories"),
        ("key_insights", None),
        ("warnings", None),
    ):
        if field:
            data[section][field] = [str(v).strip() for v in data[section][field] if str(v).strip()]
        else:
            data[section] = [str(v).strip() for v in data[section] if str(v).strip()]

    return data


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def generate_financial_advice(
    snapshot: dict,
    *,
    api_key: str | None = None,
    model: str | None = None,
    fallback_models: str | list[str] | None = None,
) -> dict:
    """Call Gemini with the calculated snapshot and return validated advice.

    Each model is retried automatically when Google reports a transient
    failure (e.g. "this model is currently experiencing high demand"). If the
    primary model stays busy, the next model from GEMINI_FALLBACK_MODELS is
    tried before the user ever sees an error.

    Raises a subclass of GeminiError with a user-friendly message on failure:
    - GeminiConfigError      key/package missing
    - GeminiUnavailableError every model is temporarily overloaded (retry later)
    - GeminiAPIError         permanent failure (bad key, no usable model...)
    - GeminiResponseError    response failed schema validation
    """
    client = _get_client(api_key)

    primary = (model or os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    if fallback_models is None:
        fallback_models = os.environ.get("GEMINI_FALLBACK_MODELS")

    models = [primary]
    known = {primary.lower()}
    for candidate in parse_fallback_models(fallback_models):
        if candidate.lower() not in known:
            known.add(candidate.lower())
            models.append(candidate)

    # google-genai is guaranteed importable here: _get_client already
    # raised a friendly GeminiConfigError otherwise.
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=FinancialAdvice,  # structured output via Pydantic
        temperature=0.4,
    )
    prompt = build_user_prompt(snapshot)

    response = None
    for model_index, model_name in enumerate(models):
        is_last_model = model_index == len(models) - 1
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                logger.info(
                    "Requesting financial advice from Gemini model %s (attempt %d)",
                    model_name,
                    attempt,
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                break  # success - leave the attempt loop
            except GeminiError:
                raise
            except Exception as exc:
                kind = _error_kind(exc)

                if kind == "other":
                    # Unknown permanent failure - retrying cannot help.
                    logger.warning(
                        "Gemini API call failed: %s: %s", type(exc).__name__, exc
                    )
                    raise GeminiAPIError(_friendly_api_error(exc)) from exc

                if kind == "auth":
                    if model_index == 0:
                        # The very first call already rejected the key.
                        logger.warning(
                            "Gemini API call failed: %s: %s", type(exc).__name__, exc
                        )
                        raise GeminiAPIError(_friendly_api_error(exc)) from exc
                    # A later model was denied: the key itself works, this
                    # particular model is just not usable with it.
                    logger.warning(
                        "Model %s is not usable with this API key (%s) - "
                        "skipping to the next model",
                        model_name,
                        type(exc).__name__,
                    )
                    break  # next model in the chain

                if kind == "model":
                    logger.warning(
                        "Model %s is not available for this API key (%s) - "
                        "skipping to the next model",
                        model_name,
                        type(exc).__name__,
                    )
                    break  # next model in the chain

                # Transient failure: retry with backoff, then switch model.
                if attempt < MAX_ATTEMPTS:
                    delay = RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "Transient Gemini failure on %s (attempt %d/%d): %s - "
                        "retrying in %.1fs",
                        model_name,
                        attempt,
                        MAX_ATTEMPTS,
                        type(exc).__name__,
                        delay,
                    )
                    _sleep(delay)
                    continue
                if is_last_model:
                    logger.warning(
                        "Gemini API call failed: %s: %s", type(exc).__name__, exc
                    )
                    raise GeminiUnavailableError(_friendly_api_error(exc)) from exc
                logger.warning(
                    "Model %s is still busy after %d attempts - trying the "
                    "next model",
                    model_name,
                    MAX_ATTEMPTS,
                )
                break  # next model in the chain
        if response is not None:
            break  # success - leave the model loop

    if response is None:
        # Every model was skipped: none of them is usable with this key.
        raise GeminiAPIError(
            "None of the configured Gemini models could be used with this "
            "API key. Run 'python list_models.py' to see the models your key "
            "can access, then update GEMINI_MODEL (and GEMINI_FALLBACK_MODELS) "
            "in your .env file."
        )

    advice = _normalise_advice(_extract_advice(response))
    logger.info("Gemini advice generated and validated successfully")
    return advice
