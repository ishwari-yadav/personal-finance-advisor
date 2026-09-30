"""Shared pytest fixtures.

The Gemini service is always mocked here so the test suite runs WITHOUT a
real API key and without touching Google's servers.
"""
import copy

import pytest

import gemini_service
from app import create_app
from models import db as _db


@pytest.fixture(autouse=True)
def _no_real_gemini_access(monkeypatch):
    """Make the whole suite hermetic - no test can ever reach Google.

    Even when the developer has a real GEMINI_API_KEY in .env (which
    config.py loads into os.environ), tests must never perform real network
    calls: they would be slow, cost quota and fail randomly whenever the
    model is briefly overloaded. Removing the key here means every test
    either uses the mock_gemini fixture (success path) or deterministically
    takes the 503 "key missing" path.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Ignore any configured fallback models so direct service-level calls in
    # tests are fully deterministic (route tests pass their own config).
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)

# A fully valid advice payload shaped exactly like the Pydantic schema.
# Two numbers are intentionally wrong so tests can prove that the app
# reconciles AI figures with the Python-calculated snapshot.
MOCK_ADVICE = {
    "budget_plan": {
        "summary": "A balanced budget that keeps essentials stable and frees up money for your goal.",
        "recommended_allocations": [
            {"category": "Rent / Housing", "current_amount": 11000, "recommended_amount": 12000,
             "reason": "Keeps your essential housing cost unchanged."},
            {"category": "Food", "current_amount": 6000, "recommended_amount": 5200,
             "reason": "Weekly meal planning can trim around 800."},
            {"category": "Transportation", "current_amount": 3000, "recommended_amount": 2600,
             "reason": "Mix public transport with walking for short trips."},
            {"category": "Entertainment", "current_amount": 2000, "recommended_amount": 1400,
             "reason": "Keep one subscription and prefer free local events."},
        ],
    },
    "spending_analysis": {
        "summary": "Essential spending dominates your budget and your savings rate is healthy.",
        "observations": ["Housing is your largest category.", "Discretionary spending is modest."],
        "high_priority_categories": ["Food", "Entertainment"],
    },
    "saving_suggestions": [
        {"suggestion": "Plan weekly meals and cook in batches.", "estimated_monthly_impact": 800,
         "priority": "high"},
        {"suggestion": "Review subscriptions you rarely use.", "estimated_monthly_impact": 300,
         "priority": "low"},
    ],
    "goal_strategy": {
        "goal_name": "Emergency fund",
        "target_amount": 59000,   # app must reconcile this to 60000
        "monthly_target": 9500,   # app must reconcile this to 10000
        "strategy": "Move the required amount to savings on payday each month.",
    },
    "monthly_summary": "You spend about half of your income and keep a healthy surplus.",
    "key_insights": ["Housing takes the largest share of spending.",
                     "You can reach your goal comfortably within the duration."],
    "warnings": [],
}

# The spec's worked example: income 50000, five expense categories.
VALID_PAYLOAD = {
    "income": 50000,
    "expenses": {
        "rent": 12000,
        "food": 6000,
        "transport": 3000,
        "utilities": 2500,
        "entertainment": 2000,
    },
    "goal_name": "Emergency fund",
    "goal_target_amount": 60000,
    "goal_duration_months": 6,
}


@pytest.fixture()
def app(tmp_path):
    """A fresh Flask app with an isolated temporary SQLite database."""
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "GEMINI_API_KEY": "",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path.as_posix()}/test.db",
        }
    )
    yield app
    with app.app_context():
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def mock_gemini(monkeypatch):
    """Replace the real Gemini call with a deterministic fake."""
    monkeypatch.setattr(
        gemini_service,
        "generate_financial_advice",
        lambda snapshot, **kwargs: copy.deepcopy(MOCK_ADVICE),
    )


@pytest.fixture()
def valid_payload():
    return copy.deepcopy(VALID_PAYLOAD)
