"""Unit tests for the deterministic financial calculations."""
import pytest

import finance_service as fs


# The worked example from the specification.
EXAMPLE_EXPENSES = {
    "rent": 12000,
    "food": 6000,
    "transport": 3000,
    "utilities": 2500,
    "entertainment": 2000,
}


class TestBasicCalculations:
    def test_total_expenses(self):
        assert fs.calculate_total_expenses(EXAMPLE_EXPENSES) == 25500

    def test_total_expenses_empty(self):
        assert fs.calculate_total_expenses({}) == 0

    def test_remaining_income(self):
        assert fs.calculate_remaining_income(50000, 25500) == 24500

    def test_remaining_income_can_be_negative(self):
        assert fs.calculate_remaining_income(20000, 25500) == -5500

    def test_savings_rate(self):
        assert fs.calculate_savings_rate(50000, 24500) == 49.0

    def test_savings_rate_negative_when_overspending(self):
        assert fs.calculate_savings_rate(20000, -5500) == -27.5

    def test_savings_rate_rejects_zero_income(self):
        with pytest.raises(ValueError):
            fs.calculate_savings_rate(0, 100)

    def test_amounts_are_rounded_to_two_decimals(self):
        # 10.006 + 20.004 = 30.01 (the total is rounded to two decimals)
        assert fs.calculate_total_expenses({"food": 10.006, "rent": 20.004}) == 30.01


class TestCategoryAnalysis:
    def test_category_percentages(self):
        percentages = fs.calculate_category_percentages(EXAMPLE_EXPENSES, 25500)
        assert percentages["rent"] == 47.06
        assert percentages["food"] == 23.53
        assert sum(percentages.values()) == pytest.approx(100, abs=0.2)

    def test_category_percentages_zero_total(self):
        percentages = fs.calculate_category_percentages({"rent": 0}, 0)
        assert percentages == {"rent": 0.0}

    def test_find_largest_expense(self):
        assert fs.find_largest_expense(EXAMPLE_EXPENSES) == ("rent", 12000)

    def test_find_largest_expense_empty(self):
        assert fs.find_largest_expense({}) is None

    def test_find_largest_expense_all_zero(self):
        assert fs.find_largest_expense({"rent": 0, "food": 0}) is None

    def test_discretionary_expenses(self):
        # entertainment + shopping + other = 2000 + 0 + 0
        assert fs.calculate_discretionary_expenses(EXAMPLE_EXPENSES) == 2000

    def test_essential_expenses(self):
        # rent + food + transport + utilities = 12000 + 6000 + 3000 + 2500
        assert fs.calculate_essential_expenses(EXAMPLE_EXPENSES) == 23500


class TestGoalRequirement:
    def test_goal_monthly_requirement(self):
        assert fs.calculate_goal_monthly_requirement(60000, 6) == 10000

    def test_goal_monthly_requirement_missing_values(self):
        assert fs.calculate_goal_monthly_requirement(None, 6) is None
        assert fs.calculate_goal_monthly_requirement(60000, None) is None
        assert fs.calculate_goal_monthly_requirement(None, None) is None

    def test_goal_monthly_requirement_invalid_duration(self):
        with pytest.raises(ValueError):
            fs.calculate_goal_monthly_requirement(60000, 0)


class TestFinancialSnapshot:
    def test_snapshot_contains_all_expected_metrics(self):
        snapshot = fs.build_financial_snapshot(
            50000, EXAMPLE_EXPENSES, "Emergency fund", 60000, 6
        )
        assert snapshot["income"] == 50000
        assert snapshot["total_expenses"] == 25500
        assert snapshot["remaining_income"] == 24500
        assert snapshot["savings_rate"] == 49.0
        assert snapshot["largest_expense_category"]["category"] == "rent"
        assert snapshot["largest_expense_category"]["label"] == "Rent / Housing"
        assert snapshot["goal"]["monthly_requirement"] == 10000
        assert snapshot["goal"]["on_track"] is True
        assert snapshot["goal"]["surplus_after_goal"] == 14500
        assert snapshot["fifty_thirty_twenty"]["savings_target"] == 10000
        assert snapshot["category_percentages"]["rent"] == 47.06

    def test_snapshot_without_goal_numbers(self):
        snapshot = fs.build_financial_snapshot(50000, EXAMPLE_EXPENSES, "General savings")
        assert snapshot["goal"]["target_amount"] is None
        assert snapshot["goal"]["duration_months"] is None
        assert snapshot["goal"]["monthly_requirement"] is None
        assert snapshot["goal"]["on_track"] is None

    def test_snapshot_when_overspending(self):
        snapshot = fs.build_financial_snapshot(
            20000, EXAMPLE_EXPENSES, "Laptop", 50000, 12
        )
        assert snapshot["remaining_income"] == -5500
        assert snapshot["savings_rate"] == -27.5
        assert snapshot["goal"]["on_track"] is False

    def test_snapshot_with_empty_expenses(self):
        snapshot = fs.build_financial_snapshot(30000, {}, "Vacation")
        assert snapshot["total_expenses"] == 0
        assert snapshot["remaining_income"] == 30000
        assert snapshot["savings_rate"] == 100.0
        assert snapshot["largest_expense_category"] is None


class TestReconcileAdvice:
    def test_goal_numbers_are_corrected_from_snapshot(self):
        snapshot = fs.build_financial_snapshot(
            50000, EXAMPLE_EXPENSES, "Emergency fund", 60000, 6
        )
        advice = {
            "goal_strategy": {
                "goal_name": "Emergency fund",
                "target_amount": 59000,      # wrong on purpose
                "monthly_target": 9500,      # wrong on purpose
                "strategy": "Save monthly.",
            },
            "budget_plan": {"recommended_allocations": []},
        }
        fixed = fs.reconcile_advice_with_calculations(advice, snapshot)
        assert fixed["goal_strategy"]["target_amount"] == 60000
        assert fixed["goal_strategy"]["monthly_target"] == 10000

    def test_current_amounts_match_snapshot_by_label(self):
        snapshot = fs.build_financial_snapshot(
            50000, EXAMPLE_EXPENSES, "Emergency fund", 60000, 6
        )
        advice = {
            "goal_strategy": {},
            "budget_plan": {
                "recommended_allocations": [
                    {"category": "Rent / Housing", "current_amount": 11000,
                     "recommended_amount": 12000, "reason": "Keep as is."},
                ]
            },
        }
        fixed = fs.reconcile_advice_with_calculations(advice, snapshot)
        assert fixed["budget_plan"]["recommended_allocations"][0]["current_amount"] == 12000

    def test_unknown_category_labels_are_left_alone(self):
        snapshot = fs.build_financial_snapshot(50000, EXAMPLE_EXPENSES, "Savings")
        advice = {
            "goal_strategy": {},
            "budget_plan": {
                "recommended_allocations": [
                    {"category": "Gifts", "current_amount": 500,
                     "recommended_amount": 300, "reason": "Trim slightly."},
                ]
            },
        }
        fixed = fs.reconcile_advice_with_calculations(advice, snapshot)
        assert fixed["budget_plan"]["recommended_allocations"][0]["current_amount"] == 500
