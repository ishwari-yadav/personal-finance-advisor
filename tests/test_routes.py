"""Route / integration tests. The Gemini service is mocked (no API key needed)."""
import json

from models import Expense, FinancialRecord, db

from tests.conftest import MOCK_ADVICE, VALID_PAYLOAD


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}


class TestHomepage:
    def test_homepage_renders(self, client):
        response = client.get("/")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Personal Finance Advisor Bot" in html
        assert "not a substitute for professional financial advice" in html
        assert 'id="finance-form"' in html
        assert 'id="analyse-btn"' in html

    def test_static_assets_are_served(self, client):
        assert client.get("/static/css/style.css").status_code == 200
        assert client.get("/static/js/app.js").status_code == 200


class TestAnalyseEndpoint:
    def test_analyse_happy_path(self, client, mock_gemini, valid_payload):
        response = client.post(
            "/analyse", data=json.dumps(valid_payload),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.get_json()

        # Response shape expected by the frontend renderer.
        for key in ("record_id", "month", "created_at", "snapshot", "advice"):
            assert key in body

        # Python-calculated metrics (the spec's worked example).
        snapshot = body["snapshot"]
        assert snapshot["income"] == 50000
        assert snapshot["total_expenses"] == 25500
        assert snapshot["remaining_income"] == 24500
        assert snapshot["savings_rate"] == 49.0
        assert snapshot["goal"]["monthly_requirement"] == 10000

        # All seven AI sections are present and populated.
        advice = body["advice"]
        for section in ("budget_plan", "spending_analysis", "saving_suggestions",
                        "goal_strategy", "monthly_summary", "key_insights", "warnings"):
            assert section in advice
        assert advice["monthly_summary"] == MOCK_ADVICE["monthly_summary"]

    def test_analyse_reconciles_ai_numbers_with_calculations(
        self, client, mock_gemini, valid_payload
    ):
        """AI-quoted goal figures must be corrected to the authoritative values."""
        body = client.post(
            "/analyse", data=json.dumps(valid_payload),
            content_type="application/json",
        ).get_json()
        strategy = body["advice"]["goal_strategy"]
        assert strategy["target_amount"] == 60000      # mock said 59000
        assert strategy["monthly_target"] == 10000     # mock said 9500

        rent_row = next(
            row for row in body["advice"]["budget_plan"]["recommended_allocations"]
            if row["category"] == "Rent / Housing"
        )
        assert rent_row["current_amount"] == 12000     # mock said 11000

    def test_analyse_saves_to_database(self, app, client, mock_gemini, valid_payload):
        client.post("/analyse", data=json.dumps(valid_payload),
                    content_type="application/json")
        with app.app_context():
            assert FinancialRecord.query.count() == 1
            record = FinancialRecord.query.first()
            assert record.income == 50000
            assert record.total_expenses == 25500
            assert record.remaining_income == 24500
            assert record.savings_rate == 49.0
            assert record.goal_name == "Emergency fund"
            assert record.goal_target_amount == 60000
            assert record.goal_duration_months == 6
            assert record.ai_summary == MOCK_ADVICE["monthly_summary"]
            stored = json.loads(record.ai_response_json)
            assert stored["goal_strategy"]["target_amount"] == 60000
            # Only the 5 non-zero expense categories are stored.
            assert Expense.query.count() == 5

    def test_analyse_without_api_key_returns_503(
        self, client, monkeypatch, valid_payload
    ):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        response = client.post(
            "/analyse", data=json.dumps(valid_payload),
            content_type="application/json",
        )
        assert response.status_code == 503
        error = response.get_json()["error"]
        assert "GEMINI_API_KEY" in error
        # The error must not leak any secret material - in any key format
        # (classic "AIza..." or the newer "AQ....").
        assert "AIza" not in error
        assert "AQ." not in error


class TestHistoryEndpoints:
    def test_history_empty(self, client):
        response = client.get("/history")
        assert response.status_code == 200
        assert response.get_json() == {"count": 0, "records": []}

    def test_history_lists_saved_analysis(self, client, mock_gemini, valid_payload):
        client.post("/analyse", data=json.dumps(valid_payload),
                    content_type="application/json")
        body = client.get("/history").get_json()
        assert body["count"] == 1
        record = body["records"][0]
        assert record["income"] == 50000
        assert record["total_expenses"] == 25500
        assert record["remaining_income"] == 24500
        assert record["savings_rate"] == 49.0
        assert record["goal_name"] == "Emergency fund"
        assert record["month"]  # "YYYY-MM"

    def test_history_detail_returns_full_analysis(
        self, client, mock_gemini, valid_payload
    ):
        saved = client.post(
            "/analyse", data=json.dumps(valid_payload),
            content_type="application/json",
        ).get_json()

        detail = client.get(f"/history/{saved['record_id']}")
        assert detail.status_code == 200
        body = detail.get_json()

        # Snapshot is rebuilt from the stored data and matches the original.
        assert body["snapshot"]["income"] == 50000
        assert body["snapshot"]["total_expenses"] == 25500
        assert body["snapshot"]["savings_rate"] == 49.0
        assert body["snapshot"]["goal"]["monthly_requirement"] == 10000

        # Stored advice matches what was returned by /analyse.
        assert body["advice"] == saved["advice"]

    def test_history_detail_not_found(self, client):
        response = client.get("/history/999")
        assert response.status_code == 404
        assert "error" in response.get_json()


class TestDatabaseModels:
    def test_tables_are_created(self, app):
        with app.app_context():
            from sqlalchemy import inspect

            inspector = inspect(db.engine)
            assert "financial_records" in inspector.get_table_names()
            assert "expenses" in inspector.get_table_names()

    def test_record_expense_relationship(self, app):
        with app.app_context():
            record = FinancialRecord(
                month="2026-09", income=50000, total_expenses=25500,
                remaining_income=24500, savings_rate=49.0, goal_name="Laptop",
                goal_target_amount=80000, goal_duration_months=10,
                ai_summary="summary", ai_response_json="{}",
            )
            record.expenses.append(Expense(category="rent", amount=12000))
            record.expenses.append(Expense(category="food", amount=6000))
            db.session.add(record)
            db.session.commit()

            fetched = db.session.get(FinancialRecord, record.id)
            assert len(fetched.expenses) == 2
            assert {e.category for e in fetched.expenses} == {"rent", "food"}

            # Deleting the record removes its expenses (cascade).
            db.session.delete(fetched)
            db.session.commit()
            assert Expense.query.count() == 0


class TestErrorHandling:
    def test_unknown_route_returns_json_404(self, client):
        response = client.get("/nope")
        assert response.status_code == 404
        assert "error" in response.get_json()

    def test_wrong_method_returns_json_405(self, client):
        response = client.get("/analyse")
        assert response.status_code == 405
        assert "error" in response.get_json()
