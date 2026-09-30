"""Database models (SQLite + SQLAlchemy).

Two related tables:

- ``FinancialRecord``: one completed financial analysis (metrics + AI output).
- ``Expense``: the individual expense categories belonging to a record.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _utcnow() -> datetime:
    """Current UTC time (used as the default for created_at)."""
    return datetime.now(timezone.utc)


class FinancialRecord(db.Model):
    """A single completed financial analysis submitted by the user."""

    __tablename__ = "financial_records"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    month = db.Column(db.String(7), nullable=False)  # "YYYY-MM"

    # Deterministic metrics calculated by finance_service.py
    income = db.Column(db.Float, nullable=False)
    total_expenses = db.Column(db.Float, nullable=False)
    remaining_income = db.Column(db.Float, nullable=False)
    savings_rate = db.Column(db.Float, nullable=False)  # percent of income

    # Goal details
    goal_name = db.Column(db.String(120), nullable=False)
    goal_target_amount = db.Column(db.Float, nullable=True)
    goal_duration_months = db.Column(db.Integer, nullable=True)

    # AI output (monthly summary kept separately for quick display)
    ai_summary = db.Column(db.Text, nullable=False)
    ai_response_json = db.Column(db.Text, nullable=False)

    # Relationship: deleting a record also deletes its expense rows.
    expenses = db.relationship(
        "Expense", back_populates="record", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """Compact serialisation used by the history list endpoint."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "month": self.month,
            "income": self.income,
            "total_expenses": self.total_expenses,
            "remaining_income": self.remaining_income,
            "savings_rate": self.savings_rate,
            "goal_name": self.goal_name,
        }

    def __repr__(self) -> str:  # helpful in logs / shell
        return f"<FinancialRecord {self.id} {self.month} goal={self.goal_name!r}>"


class Expense(db.Model):
    """One expense category amount belonging to a FinancialRecord."""

    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    financial_record_id = db.Column(
        db.Integer,
        db.ForeignKey("financial_records.id"),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(32), nullable=False)
    amount = db.Column(db.Float, nullable=False)

    record = db.relationship("FinancialRecord", back_populates="expenses")

    def __repr__(self) -> str:
        return f"<Expense {self.category}={self.amount}>"
