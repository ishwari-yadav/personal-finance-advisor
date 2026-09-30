"""Deterministic financial calculations.

Every number the user sees (and every number sent to Gemini) is calculated
here in plain, testable Python - the AI is never asked to do arithmetic.
"""
from __future__ import annotations

# Canonical expense category keys accepted by the application.
EXPENSE_CATEGORIES: tuple[str, ...] = (
    "rent",
    "food",
    "transport",
    "utilities",
    "entertainment",
    "shopping",
    "healthcare",
    "education",
    "other",
)

# Human-friendly labels (also used in the Gemini prompt and the UI table).
CATEGORY_LABELS: dict[str, str] = {
    "rent": "Rent / Housing",
    "food": "Food",
    "transport": "Transportation",
    "utilities": "Utilities",
    "entertainment": "Entertainment",
    "shopping": "Shopping",
    "healthcare": "Healthcare",
    "education": "Education",
    "other": "Other",
}

# "Wants" vs "needs" split used for the 50/30/20 rule-of-thumb comparison.
DISCRETIONARY_CATEGORIES: tuple[str, ...] = ("entertainment", "shopping", "other")
ESSENTIAL_CATEGORIES: tuple[str, ...] = (
    "rent",
    "food",
    "transport",
    "utilities",
    "healthcare",
    "education",
)


def calculate_total_expenses(expenses: dict[str, float]) -> float:
    """Sum all expense amounts."""
    return round(sum(float(amount) for amount in expenses.values()), 2)


def calculate_remaining_income(income: float, total_expenses: float) -> float:
    """Income left after expenses (may be negative when overspending)."""
    return round(float(income) - float(total_expenses), 2)


def calculate_savings_rate(income: float, remaining_income: float) -> float:
    """Remaining income as a percentage of income."""
    if income <= 0:
        raise ValueError("Income must be greater than zero to calculate the savings rate.")
    return round((float(remaining_income) / float(income)) * 100, 2)


def calculate_category_percentages(
    expenses: dict[str, float], total_expenses: float
) -> dict[str, float]:
    """Each category's share of total spending, in percent."""
    if total_expenses <= 0:
        return {category: 0.0 for category in expenses}
    return {
        category: round((float(amount) / total_expenses) * 100, 2)
        for category, amount in expenses.items()
    }


def find_largest_expense(expenses: dict[str, float]) -> tuple[str, float] | None:
    """Return (category, amount) for the biggest expense, or None if empty."""
    if not expenses:
        return None
    category, amount = max(expenses.items(), key=lambda item: item[1])
    amount = round(float(amount), 2)
    return (category, amount) if amount > 0 else None


def calculate_discretionary_expenses(expenses: dict[str, float]) -> float:
    """Total "wants" spending (entertainment, shopping, other)."""
    return round(
        sum(float(expenses.get(category, 0)) for category in DISCRETIONARY_CATEGORIES),
        2,
    )


def calculate_essential_expenses(expenses: dict[str, float]) -> float:
    """Total "needs" spending (housing, food, transport, utilities, ...)."""
    return round(
        sum(float(expenses.get(category, 0)) for category in ESSENTIAL_CATEGORIES),
        2,
    )


def calculate_goal_monthly_requirement(
    target_amount: float | None, duration_months: int | None
) -> float | None:
    """Amount to save each month to reach the goal in time.

    Returns None when either value is missing.
    """
    if target_amount is None or duration_months is None:
        return None
    if duration_months <= 0:
        raise ValueError("Goal duration must be at least one month.")
    return round(float(target_amount) / duration_months, 2)


def build_financial_snapshot(
    income: float,
    expenses: dict[str, float],
    goal_name: str,
    goal_target_amount: float | None = None,
    goal_duration_months: int | None = None,
) -> dict:
    """Build the complete, authoritative financial snapshot.

    This single dictionary is what gets sent to Gemini and rendered in the UI.
    """
    income = round(float(income), 2)
    expenses = {
        category: round(float(amount), 2)
        for category, amount in expenses.items()
    }

    total_expenses = calculate_total_expenses(expenses)
    remaining_income = calculate_remaining_income(income, total_expenses)
    savings_rate = calculate_savings_rate(income, remaining_income)
    percentages = calculate_category_percentages(expenses, total_expenses)
    largest = find_largest_expense(expenses)
    discretionary = calculate_discretionary_expenses(expenses)
    essential = calculate_essential_expenses(expenses)

    monthly_requirement = calculate_goal_monthly_requirement(
        goal_target_amount, goal_duration_months
    )

    goal: dict = {
        "name": goal_name,
        "target_amount": (
            round(float(goal_target_amount), 2)
            if goal_target_amount is not None
            else None
        ),
        "duration_months": goal_duration_months,
        "monthly_requirement": monthly_requirement,
        "on_track": None,
        "surplus_after_goal": None,
    }
    if monthly_requirement is not None:
        goal["on_track"] = remaining_income >= monthly_requirement
        goal["surplus_after_goal"] = round(remaining_income - monthly_requirement, 2)

    return {
        "income": income,
        "expenses": expenses,
        "total_expenses": total_expenses,
        "remaining_income": remaining_income,
        "savings_rate": savings_rate,
        "category_percentages": percentages,
        "largest_expense_category": (
            {
                "category": largest[0],
                "label": CATEGORY_LABELS.get(largest[0], largest[0]),
                "amount": largest[1],
                "percent_of_spending": percentages.get(largest[0], 0.0),
            }
            if largest
            else None
        ),
        "discretionary_expenses": discretionary,
        "discretionary_percent_of_income": round(
            (discretionary / income) * 100 if income > 0 else 0.0, 2
        ),
        "essential_expenses": essential,
        # Basic budget allocation figures (50/30/20 rule of thumb).
        "fifty_thirty_twenty": {
            "needs_target": round(income * 0.50, 2),
            "wants_target": round(income * 0.30, 2),
            "savings_target": round(income * 0.20, 2),
        },
        "goal": goal,
    }


# Reverse lookup: friendly label -> category key (lower-cased).
_LABEL_TO_CATEGORY: dict[str, str] = {
    label.lower(): key for key, label in CATEGORY_LABELS.items()
}


def reconcile_advice_with_calculations(advice: dict, snapshot: dict) -> dict:
    """Keep the AI's factual numbers consistent with Python's calculations.

    The AI writes the prose, but goal figures and "current spending" values
    must match the authoritative snapshot exactly.
    """
    goal = snapshot.get("goal") or {}

    strategy = advice.get("goal_strategy") or {}
    if goal.get("target_amount") is not None:
        strategy["target_amount"] = goal["target_amount"]
    if goal.get("monthly_requirement") is not None:
        strategy["monthly_target"] = goal["monthly_requirement"]
    if goal.get("name"):
        strategy["goal_name"] = goal["name"]

    for allocation in (advice.get("budget_plan") or {}).get(
        "recommended_allocations", []
    ):
        label = str(allocation.get("category", "")).strip().lower()
        category = _LABEL_TO_CATEGORY.get(label) or (
            label if label in EXPENSE_CATEGORIES else None
        )
        if category and category in snapshot["expenses"]:
            allocation["current_amount"] = snapshot["expenses"][category]

    return advice
