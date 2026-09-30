# Personal Finance Advisor Bot

An AI-powered personal finance planning assistant. Enter your monthly income,
categorized expenses and a financial goal, and the app generates a structured
financial analysis containing a **budget plan**, **spending analysis**,
**saving suggestions**, **goal strategy**, **monthly summary**, **key insights**
and **warnings**.

All arithmetic is performed by deterministic, unit-tested Python. Google Gemini
(current stable Flash model via the official `google-genai` SDK) turns those
verified numbers into personalised, natural-language guidance using a strict
structured JSON schema (Pydantic).

> This tool provides educational financial planning insights based on the
> information you provide. It is not a substitute for professional financial
> advice.

---

## Features

- Single-page, responsive web UI (HTML5 + CSS3 + vanilla JavaScript, no frameworks)
- 9 expense categories: Rent/Housing, Food, Transportation, Utilities,
  Entertainment, Shopping, Healthcare, Education, Other
- Preset goals (Emergency fund, Laptop, Vacation, Education, Investment,
  General savings) or a custom goal, with optional target amount and duration
- Deterministic Python calculations: total expenses, remaining income, savings
  rate, per-category percentages, largest category, discretionary spending,
  50/30/20 targets and the monthly amount required to hit the goal
- Gemini-powered advice with **structured JSON output** validated against a
  Pydantic schema, plus a reconciliation step that guarantees the AI never
  contradicts the calculated figures
- Automatic resilience when Google's most popular model is overloaded
  ("This model is currently experiencing high demand", HTTP 503): each model
  is retried with a short backoff, then the models listed in
  `GEMINI_FALLBACK_MODELS` are tried automatically before the user ever
  sees a friendly "try again in a moment" message
- A "Try again" button appears in the UI whenever the AI was briefly
  unavailable, so a retry is one click
- `python list_models.py` shows exactly which Gemini models your API key
  can access - handy for picking a primary model or fallback chain
- Analysis history stored in SQLite and viewable from the UI
- Robust server-side validation and friendly, safe error messages
- 83 automated tests (Gemini is mocked — no API key needed, and no test ever
  touches the network, even when a real key is configured in `.env`)

## Architecture

```
Browser (HTML/CSS/JS, Fetch API)
        |
        |  POST /analyse  (JSON)
        v
Flask app.py  ── validate input (server-side)
        |
        v
finance_service.py  ── deterministic calculations (the single source of truth)
        |
        v
gemini_service.py  ── prompt + structured JSON via google-genai (Pydantic schema)
        |             (response is validated, then reconciled with the numbers)
        v
models.py (SQLAlchemy)  ── saved to instance/finance.db (SQLite)
        |
        v
JSON response  ── rendered by app.js into the results sections + history
```

**Design principle:** Python calculates, Gemini explains. The AI is never asked
to do arithmetic, and any numeric fact it quotes about income, expenses or the
goal is reconciled against the Python-calculated snapshot before it reaches the
browser.

## Tech stack

| Layer     | Technology                                      |
|-----------|-------------------------------------------------|
| Backend   | Python 3.10+, Flask                             |
| Database  | SQLite + SQLAlchemy / Flask-SQLAlchemy          |
| AI        | Google Gemini API (`google-genai` SDK, default model `gemini-3.8-flash`, automatic fallback to `gemini-3.8-flash-lite` when busy) |
| Frontend  | HTML5, CSS3, vanilla JavaScript, Fetch API      |
| Testing   | pytest (Gemini mocked)                          |

## Project structure

```
personal-finance-advisor/
├── app.py                 # Flask app: routes, validation, error handling
├── config.py              # Configuration from environment variables (.env)
├── models.py              # SQLAlchemy models (FinancialRecord, Expense)
├── finance_service.py     # Deterministic financial calculations
├── gemini_service.py      # Gemini integration + Pydantic response schema
├── list_models.py         # Utility: list the models your API key can use
├── requirements.txt
├── pytest.ini
├── .env.example           # Template for environment variables (no secrets)
├── .gitignore
├── README.md
├── templates/
│   └── index.html         # Single-page UI
├── static/
│   ├── css/style.css
│   └── js/app.js          # Fetch API + rendering logic
├── instance/
│   └── finance.db         # SQLite database (auto-created, git-ignored)
└── tests/
    ├── conftest.py        # Fixtures + mocked Gemini advice
    ├── test_finance.py    # Calculation unit tests
    ├── test_routes.py     # Route/integration tests
    └── test_validation.py # Input validation tests
```

## Prerequisites

- Python 3.10 or newer (3.12 recommended) — check with `python --version`
- pip (bundled with Python)
- Git
- A free Gemini API key (see below)
- Optional: [ngrok](https://ngrok.com/) for a public demo URL

## Setup

### 1. Get the code and create a virtual environment

```bash
git clone <your-repo-url>
cd personal-finance-advisor

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Get a Gemini API key

1. Go to **https://aistudio.google.com/** and sign in with a Google account.
2. Click **"Get API key"** (or *API keys* in the left menu) → **"Create API key"**.
3. Copy the generated key. The free tier is enough for this project.
   Keys come in two formats - the classic `AIza...` and the newer `AQ....` -
   both work; just paste the whole key into `.env`.

### 4. Configure the environment file

```bash
cp .env.example .env
```

Then open `.env` and fill in your key:

```
GEMINI_API_KEY=paste_your_real_key_here
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODELS=gemini-3.8-flash-lite
FLASK_ENV=development
SECRET_KEY=any_random_string_for_local_development
```

`GEMINI_MODEL` is fully configurable — change it in `.env` any time without
touching the source code. `GEMINI_FALLBACK_MODELS` (comma-separated) lists
the models the app automatically switches to when the primary model is
overloaded; run `python list_models.py` at any time to see which models
your key can actually access.

### 5. Database setup

Nothing to do. On first start the app automatically creates
`instance/finance.db` and all tables.

## Running locally

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.
(Equivalent alternative: `flask --app app run --port 5000`.)

## Testing

The test suite mocks the Gemini service, so **no API key is required**:

```bash
pytest
# or, more verbose:
python -m pytest -v
```

83 tests cover financial calculations, input validation, the health endpoint,
the analyse endpoint, database models, the history API and Gemini error
handling (automatic retries, model fallbacks, transient vs permanent
failures, safe error messages).

## Exposing the app with ngrok

With the Flask server running on port 5000, in a second terminal:

```bash
# one-time setup
ngrok config add-authtoken <your-ngrok-authtoken>

# start the tunnel
ngrok http 5000
```

ngrok prints a public HTTPS URL (e.g. `https://xxxx.ngrok-free.app`) that you
can open from any device — ideal for a viva demo.

## Git / GitHub setup

The repo already contains a `.gitignore` that excludes `.env`, `.venv/`,
`instance/`, `*.db`, `__pycache__/` and editor files.

```bash
git init                      # already done if you cloned
git add .
git status                    # verify .env / .venv / instance are NOT listed
git commit -m "Personal Finance Advisor Bot"
git branch -M main
git remote add origin https://github.com/<your-username>/personal-finance-advisor.git
git push -u origin main
```

## API reference

| Method | Route            | Description                                    |
|--------|------------------|------------------------------------------------|
| GET    | `/`              | Main single-page application                   |
| POST   | `/analyse`       | Submit finances, get full analysis (JSON)      |
| GET    | `/history`       | List the 50 most recent saved analyses         |
| GET    | `/history/<id>`  | One saved analysis (snapshot + stored advice)  |
| GET    | `/health`        | `{"status": "ok"}` health check                |

Example `POST /analyse` body:

```json
{
  "income": 50000,
  "expenses": {"rent": 12000, "food": 6000, "transport": 3000,
               "utilities": 2500, "entertainment": 2000},
  "goal_name": "Emergency fund",
  "goal_target_amount": 60000,
  "goal_duration_months": 6
}
```

## Example usage

1. Enter **Monthly income** = `50000`.
2. Enter expenses: Rent `12000`, Food `6000`, Transportation `3000`,
   Utilities `2500`, Entertainment `2000`.
3. Choose goal **Emergency fund**, target `60000`, duration `6` months.
4. Click **Analyse my finances**.
5. The snapshot shows: total expenses `25,500`, remaining `24,500`,
   savings rate `49%`, goal requirement `10,000`/month.
6. Below it, Gemini's budget table, spending analysis, saving suggestions,
   goal strategy, monthly summary, insights and any warnings appear —
   all consistent with those numbers.
7. The analysis is saved automatically; click **View** in *Recent analyses*
   to reload it later.

## Security notes

- The API key lives **only** in `.env`, which is git-ignored — never in source.
- `.env.example` is committed as a template with **no** real secrets.
- All input is validated server-side; the browser is never trusted alone.
- Error messages returned to the browser never contain secrets or stack traces;
  technical details stay in the server log.
- SQLite database, virtual environment and caches are never committed.

## Troubleshooting

| Problem                                   | Fix                                                                 |
|-------------------------------------------|----------------------------------------------------------------------|
| `503 — The Gemini API key is missing`     | Create `.env` from `.env.example` and set `GEMINI_API_KEY`, restart. |
| `503 — Gemini temporarily unavailable`    | The model is overloaded on Google's side. The app already retried and |
|                                           | tried the fallback models; click "Try again" (it usually clears in a |
|                                           | few minutes), or run `python list_models.py` and switch `GEMINI_MODEL` |
|                                           | / `GEMINI_FALLBACK_MODELS` in `.env` to a model with free capacity.  |
| `502 — API key was rejected`              | Re-copy the key from Google AI Studio; check for typos/whitespace.   |
| `502 — quota exhausted`                   | Free-tier limit hit; wait a minute and retry.                        |
| `Address already in use` (port 5000)      | Stop the old process, or run `flask --app app run --port 5001`.      |
| `ModuleNotFoundError`                     | Activate the virtualenv and run `pip install -r requirements.txt`.   |
| Tests fail with import errors             | Run `pytest` from the project root (a `pytest.ini` is provided).     |
| Database issues                           | Delete `instance/finance.db` — it is recreated automatically.        |

## Future improvements

- Monthly trend charts across saved analyses
- CSV import of bank statements (user-uploaded, never auto-fetched)
- Multi-user support with simple accounts
- Recurring budgets and month-over-month comparison
- Export analysis to PDF

## Disclaimer

This is an educational personal-finance planning tool. It does not provide
regulated financial advice, does not recommend specific financial products,
and has no access to your bank accounts or transaction data.
