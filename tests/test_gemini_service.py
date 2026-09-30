"""Tests for Gemini error handling: retries and transient vs permanent failures.

These tests fake the Gemini client, so no API key and no network access are
needed. They verify the behaviour users actually hit in the wild:

- brief "high demand" 503 spikes from Google are retried automatically
- a persistent overload surfaces as a friendly 503 "try again" response
- permanent errors (e.g. a rejected key) fail fast as 502, without wasting
  retries
"""
import copy
import json
from types import SimpleNamespace

import pytest

import finance_service
import gemini_service
from gemini_service import FinancialAdvice
from tests.conftest import MOCK_ADVICE, VALID_PAYLOAD

# Realistic error messages, shaped like the ones google-genai raises.
TRANSIENT = Exception(
    "ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': "
    "'This model is currently experiencing high demand. Spikes in demand "
    "are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}"
)
PERMANENT = Exception(
    "ClientError: 400 Bad Request. API key not valid. "
    "Please pass a valid API key."
)
NOT_FOUND = Exception(
    "ClientError: 404 NOT_FOUND. "
    "models/gemini-x is not found for API version v1beta."
)
AUTH_ERROR = Exception(
    "ClientError: 401 UNAUTHENTICATED. API key not valid. "
    "Please pass a valid API key."
)


def _snapshot():
    return finance_service.build_financial_snapshot(
        VALID_PAYLOAD["income"],
        VALID_PAYLOAD["expenses"],
        VALID_PAYLOAD["goal_name"],
        VALID_PAYLOAD["goal_target_amount"],
        VALID_PAYLOAD["goal_duration_months"],
    )


def _success_response():
    """A Gemini response that already parsed into a valid FinancialAdvice."""
    return SimpleNamespace(
        parsed=FinancialAdvice.model_validate(copy.deepcopy(MOCK_ADVICE))
    )


class FakeModels:
    """Records calls; raises the given outcomes in order (last one repeats)."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        outcome = (
            self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


class FakeModelsByModel:
    """Per-model outcomes: {model_name: [outcome, ...]}; last repeats."""

    def __init__(self, outcomes_by_model):
        self._outcomes = {name: list(seq) for name, seq in outcomes_by_model.items()}
        self.calls = []

    def generate_content(self, model=None, **kwargs):
        self.calls.append(model)
        outcomes = self._outcomes[model]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClientByModel:
    def __init__(self, outcomes_by_model):
        self.models = FakeModelsByModel(outcomes_by_model)


@pytest.fixture()
def sleeps(monkeypatch):
    """Collect retry backoff waits instead of actually sleeping."""
    recorded = []
    monkeypatch.setattr(gemini_service, "_sleep", recorded.append)
    return recorded


class TestTransientErrorClassification:
    def test_overloaded_model_is_transient(self):
        assert gemini_service._is_transient_error(TRANSIENT) is True

    def test_quota_error_is_transient(self):
        error = Exception("429 RESOURCE_EXHAUSTED: quota limit exceeded")
        assert gemini_service._is_transient_error(error) is True

    def test_bad_key_is_not_transient(self):
        assert gemini_service._is_transient_error(PERMANENT) is False

    def test_unrelated_failure_is_not_transient(self):
        assert gemini_service._is_transient_error(Exception("boom")) is False


class TestRetryBehaviour:
    def test_transient_failures_are_retried_until_success(
        self, monkeypatch, sleeps
    ):
        client = FakeClient([TRANSIENT, TRANSIENT, _success_response()])
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        advice = gemini_service.generate_financial_advice(_snapshot(), api_key="x")

        assert advice["monthly_summary"] == MOCK_ADVICE["monthly_summary"]
        assert client.models.calls == 3          # 1 initial call + 2 retries
        assert sleeps == [1.5, 3.0]              # backoff between attempts

    def test_persistent_overload_raises_unavailable_after_retries(
        self, monkeypatch, sleeps
    ):
        client = FakeClient([TRANSIENT])
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        with pytest.raises(gemini_service.GeminiUnavailableError) as excinfo:
            gemini_service.generate_financial_advice(_snapshot(), api_key="x")

        assert "temporarily" in str(excinfo.value)
        assert client.models.calls == gemini_service.MAX_ATTEMPTS
        assert len(sleeps) == gemini_service.MAX_ATTEMPTS - 1

    def test_permanent_error_fails_fast_without_retries(
        self, monkeypatch, sleeps
    ):
        client = FakeClient([PERMANENT])
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        with pytest.raises(gemini_service.GeminiAPIError):
            gemini_service.generate_financial_advice(_snapshot(), api_key="x")

        assert client.models.calls == 1          # no retries for permanent errors
        assert sleeps == []


class TestRouteErrorMapping:
    def test_overloaded_gemini_returns_503_try_again(self, client, monkeypatch, sleeps):
        client.application.config["GEMINI_API_KEY"] = "AQ.simulated_key_do_not_leak"
        captured = {}

        def fake_get_client(api_key=None):
            captured["key"] = api_key
            return FakeClient([TRANSIENT])

        monkeypatch.setattr(gemini_service, "_get_client", fake_get_client)
        response = client.post(
            "/analyse",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json",
        )
        assert response.status_code == 503
        assert "temporarily" in response.get_json()["error"]
        # The response never leaks the key - in either key format.
        assert "AQ.simulated_key_do_not_leak" not in response.get_json()["error"]
        assert "AIza" not in response.get_json()["error"]

    def test_rejected_api_key_returns_502(self, client, monkeypatch, sleeps):
        client.application.config["GEMINI_API_KEY"] = "AQ.simulated_key_do_not_leak"

        def fake_get_client(api_key=None):
            assert api_key == "AQ.simulated_key_do_not_leak"  # plumbed through
            return FakeClient([PERMANENT])

        monkeypatch.setattr(gemini_service, "_get_client", fake_get_client)
        response = client.post(
            "/analyse",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json",
        )
        assert response.status_code == 502
        assert "GEMINI_API_KEY" in response.get_json()["error"]
        assert "AQ.simulated_key_do_not_leak" not in response.get_json()["error"]
        assert "AIza" not in response.get_json()["error"]


PRIMARY = "gemini-3.8-flash"
FALLBACK = "gemini-3.8-flash-lite"


class TestModelFallback:
    """When the primary model is busy, the app must switch models itself."""

    def test_busy_primary_falls_back_to_next_model(self, monkeypatch, sleeps):
        client = FakeClientByModel(
            {PRIMARY: [TRANSIENT], FALLBACK: [_success_response()]}
        )
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        advice = gemini_service.generate_financial_advice(
            _snapshot(), api_key="x", model=PRIMARY, fallback_models=FALLBACK
        )

        assert advice["monthly_summary"] == MOCK_ADVICE["monthly_summary"]
        assert client.models.calls == [PRIMARY, PRIMARY, PRIMARY, FALLBACK]
        assert sleeps == [1.5, 3.0]  # backoff only while retrying the primary

    def test_unknown_fallback_model_is_skipped(self, monkeypatch, sleeps):
        other = "gemini-3.5-flash"
        client = FakeClientByModel(
            {
                PRIMARY: [TRANSIENT],
                FALLBACK: [NOT_FOUND],
                other: [_success_response()],
            }
        )
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        advice = gemini_service.generate_financial_advice(
            _snapshot(),
            api_key="x",
            model=PRIMARY,
            fallback_models=f"{FALLBACK}, {other}",
        )
        assert advice["monthly_summary"] == MOCK_ADVICE["monthly_summary"]
        assert client.models.calls[-1] == other

    def test_all_models_busy_raises_unavailable(self, monkeypatch, sleeps):
        client = FakeClientByModel({PRIMARY: [TRANSIENT], FALLBACK: [TRANSIENT]})
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        with pytest.raises(gemini_service.GeminiUnavailableError):
            gemini_service.generate_financial_advice(
                _snapshot(), api_key="x", model=PRIMARY, fallback_models=FALLBACK
            )
        assert client.models.calls == [PRIMARY] * 3 + [FALLBACK] * 3
        assert sleeps == [1.5, 3.0, 1.5, 3.0]

    def test_rejected_key_fails_fast_before_fallbacks(self, monkeypatch, sleeps):
        client = FakeClientByModel({PRIMARY: [AUTH_ERROR]})
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        with pytest.raises(gemini_service.GeminiAPIError):
            gemini_service.generate_financial_advice(
                _snapshot(), api_key="x", model=PRIMARY, fallback_models=FALLBACK
            )
        assert client.models.calls == [PRIMARY]  # fallbacks cannot fix a bad key
        assert sleeps == []

    def test_denied_fallback_is_skipped_not_fatal(self, monkeypatch, sleeps):
        """A fallback the key may not use is skipped; the key still works."""
        other = "gemini-3.5-flash"
        client = FakeClientByModel(
            {
                PRIMARY: [TRANSIENT],
                FALLBACK: [AUTH_ERROR],
                other: [_success_response()],
            }
        )
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        advice = gemini_service.generate_financial_advice(
            _snapshot(),
            api_key="x",
            model=PRIMARY,
            fallback_models=f"{FALLBACK},{other}",
        )
        assert advice["monthly_summary"] == MOCK_ADVICE["monthly_summary"]
        assert client.models.calls[-1] == other

    def test_missing_primary_model_tries_fallback(self, monkeypatch, sleeps):
        client = FakeClientByModel(
            {PRIMARY: [NOT_FOUND], FALLBACK: [_success_response()]}
        )
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        advice = gemini_service.generate_financial_advice(
            _snapshot(), api_key="x", model=PRIMARY, fallback_models=FALLBACK
        )
        assert client.models.calls == [PRIMARY, FALLBACK]  # 404 is not retried
        assert sleeps == []

    def test_no_usable_model_raises_api_error_with_hint(self, monkeypatch, sleeps):
        client = FakeClientByModel({PRIMARY: [NOT_FOUND], FALLBACK: [NOT_FOUND]})
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        with pytest.raises(gemini_service.GeminiAPIError) as excinfo:
            gemini_service.generate_financial_advice(
                _snapshot(), api_key="x", model=PRIMARY, fallback_models=FALLBACK
            )
        assert "list_models.py" in str(excinfo.value)

    def test_fallback_equal_to_primary_is_not_tried_twice(self, monkeypatch, sleeps):
        client = FakeClientByModel({PRIMARY: [TRANSIENT]})
        monkeypatch.setattr(gemini_service, "_get_client", lambda api_key=None: client)

        with pytest.raises(gemini_service.GeminiUnavailableError):
            gemini_service.generate_financial_advice(
                _snapshot(), api_key="x", model=PRIMARY, fallback_models=PRIMARY
            )
        assert client.models.calls == [PRIMARY] * 3  # deduplicated


class TestParseFallbackModels:
    def test_empty_and_none(self):
        assert gemini_service.parse_fallback_models(None) == []
        assert gemini_service.parse_fallback_models("") == []
        assert gemini_service.parse_fallback_models(" , ,") == []

    def test_splits_strips_and_deduplicates(self):
        assert gemini_service.parse_fallback_models("b, a ,a, c") == ["b", "a", "c"]
        assert gemini_service.parse_fallback_models(["x", "X ", "y"]) == ["x", "y"]
