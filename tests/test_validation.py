"""Tests for server-side input validation (the browser is never trusted alone)."""
import json

from app import validate_financial_input


class TestValidateFinancialInputDirectly:
    def test_valid_payload_is_normalised(self, valid_payload):
        result = validate_financial_input(valid_payload)
        assert result["income"] == 50000.0
        assert result["expenses"]["rent"] == 12000.0
        assert result["goal_name"] == "Emergency fund"
        assert result["goal_target_amount"] == 60000.0
        assert result["goal_duration_months"] == 6

    def test_missing_expenses_defaults_to_empty(self):
        result = validate_financial_input(
            {"income": 30000, "goal_name": "Vacation"}
        )
        assert result["expenses"] == {}
        assert result["goal_target_amount"] is None
        assert result["goal_duration_months"] is None

    def test_non_dict_body_rejected(self):
        import pytest
        from app import InputValidationError

        with pytest.raises(InputValidationError):
            validate_financial_input([1, 2, 3])


def post(client, payload):
    return client.post(
        "/analyse", data=json.dumps(payload), content_type="application/json"
    )


class TestBodyValidation:
    def test_invalid_json_rejected(self, client):
        response = client.post(
            "/analyse", data="{not valid json", content_type="application/json"
        )
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_empty_body_rejected(self, client):
        response = client.post("/analyse", data=None, content_type="application/json")
        assert response.status_code == 400
        assert "error" in response.get_json()


class TestIncomeValidation:
    def test_income_missing(self, client, valid_payload):
        del valid_payload["income"]
        body = post(client, valid_payload).get_json()
        assert "income" in body["error"].lower()

    def test_income_zero(self, client, valid_payload):
        valid_payload["income"] = 0
        assert "greater than zero" in post(client, valid_payload).get_json()["error"]

    def test_income_negative(self, client, valid_payload):
        valid_payload["income"] = -100
        assert post(client, valid_payload).status_code == 400

    def test_income_string_rejected(self, client, valid_payload):
        valid_payload["income"] = "50000"
        body = post(client, valid_payload).get_json()
        assert "must be a number" in body["error"]

    def test_income_boolean_rejected(self, client, valid_payload):
        valid_payload["income"] = True
        assert post(client, valid_payload).status_code == 400

    def test_income_nan_rejected(self, client, valid_payload):
        payload = json.loads(json.dumps(valid_payload).replace("50000", "NaN"))
        assert post(client, payload).status_code == 400


class TestExpenseValidation:
    def test_expense_negative(self, client, valid_payload):
        valid_payload["expenses"]["food"] = -50
        body = post(client, valid_payload).get_json()
        assert "cannot be negative" in body["error"]

    def test_expense_unknown_category(self, client, valid_payload):
        valid_payload["expenses"]["groceries"] = 1000
        body = post(client, valid_payload).get_json()
        assert "Unknown expense category" in body["error"]

    def test_expenses_wrong_type(self, client, valid_payload):
        valid_payload["expenses"] = ["rent", 12000]
        assert post(client, valid_payload).status_code == 400

    def test_expense_string_amount_rejected(self, client, valid_payload):
        valid_payload["expenses"]["food"] = "6000"
        assert post(client, valid_payload).status_code == 400


class TestGoalValidation:
    def test_goal_name_missing(self, client, valid_payload):
        del valid_payload["goal_name"]
        body = post(client, valid_payload).get_json()
        assert "goal" in body["error"].lower()

    def test_goal_name_empty(self, client, valid_payload):
        valid_payload["goal_name"] = "   "
        assert post(client, valid_payload).status_code == 400

    def test_goal_name_too_long(self, client, valid_payload):
        valid_payload["goal_name"] = "x" * 121
        assert post(client, valid_payload).status_code == 400

    def test_goal_target_negative(self, client, valid_payload):
        valid_payload["goal_target_amount"] = -1
        assert post(client, valid_payload).status_code == 400

    def test_goal_duration_zero(self, client, valid_payload):
        valid_payload["goal_duration_months"] = 0
        body = post(client, valid_payload).get_json()
        assert "at least 1 month" in body["error"]

    def test_goal_duration_fractional(self, client, valid_payload):
        valid_payload["goal_duration_months"] = 2.5
        body = post(client, valid_payload).get_json()
        assert "whole number" in body["error"]

    def test_goal_duration_string_rejected(self, client, valid_payload):
        valid_payload["goal_duration_months"] = "six"
        assert post(client, valid_payload).status_code == 400

    def test_duration_without_target_rejected(self, client, valid_payload):
        del valid_payload["goal_target_amount"]
        body = post(client, valid_payload).get_json()
        assert "target amount" in body["error"]

    def test_target_without_duration_is_allowed(
        self, client, mock_gemini, valid_payload
    ):
        """A target without a duration is valid: no monthly requirement then."""
        del valid_payload["goal_duration_months"]
        response = post(client, valid_payload)
        assert response.status_code == 200
        goal = response.get_json()["snapshot"]["goal"]
        assert goal["target_amount"] == 60000
        assert goal["duration_months"] is None
        assert goal["monthly_requirement"] is None
