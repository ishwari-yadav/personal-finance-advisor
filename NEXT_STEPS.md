# NEXT STEPS - commands to run

You received `personal-finance-advisor.zip`. Follow these steps in order.
Commands are shown for macOS/Linux; Windows equivalents are noted where they
differ. You need Python 3.10 or newer (check with `python --version`).

## 1. Unzip the project

```bash
unzip personal-finance-advisor.zip
cd personal-finance-advisor
```

Windows: right-click the zip > "Extract All", then open the folder in
PowerShell or CMD.

## 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 3. Install the dependencies

```bash
pip install -r requirements.txt
```

## 4. Add your Gemini API key (required for AI advice)

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Then open `.env` in any editor and fill in:

```
GEMINI_API_KEY=your_real_key_here
```

Free key (takes 2 minutes): go to https://aistudio.google.com/, sign in with
a Google account, click "Get API key" > "Create API key", and copy it into
`.env`. Keys come in two formats - classic `AIza...` and newer `AQ....` -
both work; paste the whole key. Optional: change `GEMINI_MODEL` or
`GEMINI_FALLBACK_MODELS` in the same file (defaults: `gemini-3.8-flash`
with `gemini-3.8-flash-lite` as fallback when the primary model is busy).

To see exactly which models your key can access at any time:

```bash
python list_models.py
```

## 5. Run the test suite (no API key needed)

```bash
pytest -v
```

Expected result: `83 passed`. The suite is fully self-contained: even with a
real `GEMINI_API_KEY` in your `.env`, no test contacts Google, so the result
is always the same.

## 6. Start the app

```bash
python app.py
```

Then open http://127.0.0.1:5000 in your browser. The first start creates
`instance/finance.db` automatically - there is no manual database setup.

Quick check that the server is alive (from a second terminal):

```bash
curl http://127.0.0.1:5000/health
# -> {"status":"ok"}
```

## 7. Try one full analysis

1. Monthly income: `50000`
2. Expenses: Rent `12000`, Food `6000`, Transportation `3000`,
   Utilities `2500`, Entertainment `2000`
3. Goal: Emergency fund, target `60000`, duration `6` months
4. Click "Analyse my finances" - the snapshot should show total expenses
   `25,500`, remaining income `24,500` and a savings rate of `49%`.
5. Scroll down for the AI budget plan, spending analysis, saving suggestions
   and goal strategy, then check "Recent analyses" at the bottom: the run is
   saved and can be re-opened at any time.

Note: the first analysis can take up to half a minute. If Google's most
popular model is briefly overloaded, the app automatically retries and
switches to a fallback model; if every model is busy it shows a "Try again"
button - spikes usually clear within a few minutes.

## 8. Optional: public demo URL with ngrok

With the app running (step 6), in a second terminal:

```bash
ngrok config add-authtoken <your-ngrok-authtoken>   # one-time setup
ngrok http 5000
```

ngrok prints a public HTTPS URL you can open from any device - ideal for a
viva or presentation demo.

## 9. Optional: push to GitHub

Create an empty repository on https://github.com (no README, no license),
then run:

```bash
git init
git add .
git status        # confirm .env, .venv/ and instance/ are NOT listed
git commit -m "Personal Finance Advisor Bot"
git branch -M main
git remote add origin https://github.com/<your-username>/personal-finance-advisor.git
git push -u origin main
```

## If something goes wrong

| Problem                          | Fix                                                                     |
|----------------------------------|-------------------------------------------------------------------------|
| `ModuleNotFoundError`            | Virtualenv not active, or step 3 was not run.                           |
| `503` Gemini key missing         | Create `.env` from `.env.example`, set `GEMINI_API_KEY`, restart.       |
| `503` Gemini temporarily busy    | Google-side overload at peak hours. The app already retried and tried  |
|                                  | fallbacks; click "Try again" in a few minutes, or run                 |
|                                  | `python list_models.py` and set `GEMINI_MODEL` to a model with capacity |
| `502` API key rejected           | Re-copy the key from Google AI Studio; check for typos or spaces.       |
| `Address already in use` (5000)  | Another server is running: `flask --app app run --port 5001`.           |
| Old or strange saved data        | Stop the app, delete `instance/finance.db`, start again.                |
| Tests fail with import errors    | Run `pytest` from the project root (a `pytest.ini` is provided).        |
