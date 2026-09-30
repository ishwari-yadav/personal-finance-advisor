"""Personal Finance Advisor Bot - Flask application.

Routes
------
GET  /              main single-page UI
POST /analyse       validate input -> calculate -> ask Gemini -> save -> respond
GET  /history       list recent saved analyses
GET  /history/<id>  one saved analysis
GET  /health        simple health check

Run with:  python app.py   (serves on http://127.0.0.1:5000)
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

import finance_service
import gemini_service
from config import Config
from finance_service import EXPENSE_CATEGORIES
from models import Expense, FinancialRecord, db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Sensible upper bounds so absurd values never reach the database or Gemini.
MAX_AMOUNT = 10_000_000_000.0
MAX_GOAL_NAME_LENGTH = 120
MAX_DURATION_MONTHS = 600


class InputValidationError(ValueError):
    """Raised when submitted financial data fails server-side validation."""


# --------------------------------------------------------------------------
# Server-side validation (the browser is never trusted on its own)
# --------------------------------------------------------------------------

def _validate_number(value, label: str, *, positive: bool = False) -> float:
    """Return ``value`` as a clean float or raise InputValidationError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputValidationError(f"{label} must be a number.")
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise InputValidationError(f"{label} must be a valid number.")
    if positive and number <= 0:
        raise InputValidationError(f"{label} must be greater than zero.")
    if number < 0:
        raise InputValidationError(f"{label} cannot be negative.")
    if number > MAX_AMOUNT:
        raise InputValidationError(f"{label} is unrealistically large.")
    return round(number, 2)


def _validate_duration(value) -> int:
    """Validate a goal duration in whole months (>= 1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputValidationError("Target duration must be a number of months.")
    if isinstance(value, float) and not float(value).is_integer():
        raise InputValidationError("Target duration must be a whole number of months.")
    months = int(value)
    if months < 1:
        raise InputValidationError("Target duration must be at least 1 month.")
    if months > MAX_DURATION_MONTHS:
        raise InputValidationError(
            f"Target duration cannot be longer than {MAX_DURATION_MONTHS} months."
        )
    return months


def validate_financial_input(data) -> dict:
    """Validate and normalise the JSON body of POST /analyse.

    Raises InputValidationError with a user-friendly message on any problem.
    """
    if not isinstance(data, dict):
        raise InputValidationError("Request body must be a JSON object.")

    # --- income ---
    if data.get("income") is None:
        raise InputValidationError("Monthly income is required.")
    income = _validate_number(data["income"], "Monthly income", positive=True)

    # --- expenses ---
    raw_expenses = data.get("expenses")
    if raw_expenses is None:
        raw_expenses = {}
    if not isinstance(raw_expenses, dict):
        raise InputValidationError("Expenses must be provided as category-amount pairs.")
    expenses: dict[str, float] = {}
    for category, amount in raw_expenses.items():
        if category not in EXPENSE_CATEGORIES:
            valid = ", ".join(EXPENSE_CATEGORIES)
            raise InputValidationError(
                f"Unknown expense category '{category}'. Valid categories: {valid}."
            )
        expenses[category] = _validate_number(amount, f"Expense '{category}'")

    # --- goal ---
    goal_name = data.get("goal_name")
    if not isinstance(goal_name, str) or not goal_name.strip():
        raise InputValidationError("Please provide a financial goal name.")
    goal_name = goal_name.strip()
    if len(goal_name) > MAX_GOAL_NAME_LENGTH:
        raise InputValidationError(
            f"Goal name is too long (max {MAX_GOAL_NAME_LENGTH} characters)."
        )

    goal_target = data.get("goal_target_amount")
    if goal_target is not None:
        goal_target = _validate_number(goal_target, "Goal target amount")

    goal_duration = data.get("goal_duration_months")
    if goal_duration is not None:
        goal_duration = _validate_duration(goal_duration)
        if goal_target is None:
            raise InputValidationError(
                "Please provide a target amount when specifying a target duration."
            )

    return {
        "income": income,
        "expenses": expenses,
        "goal_name": goal_name,
        "goal_target_amount": goal_target,
        "goal_duration_months": goal_duration,
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _save_analysis(snapshot: dict, advice: dict) -> FinancialRecord:
    """Persist one completed analysis (record + expense rows) in SQLite."""
    goal = snapshot["goal"]
    record = FinancialRecord(
        month=datetime.now(timezone.utc).strftime("%Y-%m"),
        income=snapshot["income"],
        total_expenses=snapshot["total_expenses"],
        remaining_income=snapshot["remaining_income"],
        savings_rate=snapshot["savings_rate"],
        goal_name=goal["name"],
        goal_target_amount=goal["target_amount"],
        goal_duration_months=goal["duration_months"],
        ai_summary=advice.get("monthly_summary", ""),
        ai_response_json=json.dumps(advice),
    )
    for category, amount in snapshot["expenses"].items():
        if amount > 0:
            record.expenses.append(Expense(category=category, amount=amount))
    db.session.add(record)
    db.session.commit()
    return record


def _analysis_response(record: FinancialRecord, snapshot: dict, advice: dict) -> dict:
    """Common response shape used by POST /analyse and GET /history/<id>."""
    return {
        "record_id": record.id,
        "month": record.month,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "snapshot": snapshot,
        "advice": advice,
    }


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------

def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the app; database tables are created on startup."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # Make sure instance/ exists so SQLite can create finance.db there.
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    # ------------------------------ routes ------------------------------

    @app.route("/")
    def index():
        """Render the main single-page application."""
        return render_template("index.html")

    @app.route("/health")
    def health():
        """Simple health check."""
        return jsonify({"status": "ok"})

    @app.route("/analyse", methods=["POST"])
    def analyse():
        """Full pipeline: validate -> calculate -> Gemini -> validate -> save."""
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "Request body must be valid JSON."}), 400

        try:
            payload = validate_financial_input(data)
        except InputValidationError as exc:
            return jsonify({"error": str(exc)}), 400

        # 1) Deterministic calculations (Python, not AI).
        snapshot = finance_service.build_financial_snapshot(**payload)

        # 2) Ask Gemini for the structured, natural-language advice.
        #    Transient failures (model briefly overloaded) are retried inside
        #    the service; if the primary model stays busy, the fallback models
        #    are tried before giving up with a friendly 503 "try again".
        try:
            advice = gemini_service.generate_financial_advice(
                snapshot,
                api_key=app.config.get("GEMINI_API_KEY", ""),
                model=app.config.get("GEMINI_MODEL"),
                fallback_models=app.config.get("GEMINI_FALLBACK_MODELS"),
            )
        except (
            gemini_service.GeminiConfigError,
            gemini_service.GeminiUnavailableError,
        ) as exc:
            return jsonify({"error": str(exc)}), 503
        except gemini_service.GeminiError as exc:
            return jsonify({"error": str(exc)}), 502

        # 3) Keep the AI's factual numbers aligned with our calculations.
        advice = finance_service.reconcile_advice_with_calculations(advice, snapshot)

        # 4) Save the completed analysis.
        try:
            record = _save_analysis(snapshot, advice)
        except Exception:
            logger.exception("Could not save the analysis to the database")
            db.session.rollback()
            return jsonify(
                {
                    "error": "The analysis was generated but could not be saved. "
                    "Please try again."
                }
            ), 500

        logger.info("Saved financial analysis record %s", record.id)
        return jsonify(_analysis_response(record, snapshot, advice)), 200

    @app.route("/history")
    def history():
        """List the most recent saved analyses."""
        records = (
            FinancialRecord.query.order_by(
                FinancialRecord.created_at.desc(), FinancialRecord.id.desc()
            )
            .limit(50)
            .all()
        )
        return jsonify({"count": len(records), "records": [r.to_dict() for r in records]})

    @app.route("/history/<int:record_id>")
    def history_detail(record_id: int):
        """Return one saved analysis (recomputed snapshot + stored AI advice)."""
        record = db.session.get(FinancialRecord, record_id)
        if record is None:
            return jsonify({"error": "Analysis not found."}), 404

        expenses = {expense.category: expense.amount for expense in record.expenses}
        snapshot = finance_service.build_financial_snapshot(
            record.income,
            expenses,
            record.goal_name,
            record.goal_target_amount,
            record.goal_duration_months,
        )
        advice = json.loads(record.ai_response_json)
        return jsonify(_analysis_response(record, snapshot, advice)), 200

    # --------------------------- error handlers --------------------------

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        """Return JSON errors (e.g. 404/405) for API-friendly responses."""
        return jsonify({"error": error.description}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        """Last-resort handler: log details, show a safe message."""
        logger.exception("Unexpected server error")
        return jsonify(
            {"error": "Something went wrong on our side. Please try again."}
        ), 500

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=application.config["DEBUG"])
