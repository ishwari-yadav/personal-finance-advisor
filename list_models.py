"""List the Gemini models your API key can access.

Google occasionally runs out of free-tier capacity for the most popular
model ("This model is currently experiencing high demand" / HTTP 503).
When that happens you have two options:

1. Do nothing - the app automatically retries and falls back to the models
   listed in GEMINI_FALLBACK_MODELS.
2. Pick a different model from this list and set it as GEMINI_MODEL (or as
   GEMINI_FALLBACK_MODELS) in your .env file.

Usage (from the project root, with your .env in place):

    python list_models.py
"""
from __future__ import annotations

import os
import sys

from config import Config  # loads .env automatically


def main() -> int:
    api_key = (Config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("No GEMINI_API_KEY found.")
        print("Add it to your .env file first (see .env.example), then retry.")
        return 1

    try:
        from google import genai
    except ImportError:
        print("The google-genai package is not installed.")
        print("Run: pip install -r requirements.txt")
        return 1

    print("Asking Google which models your key can use...\n")
    try:
        client = genai.Client(api_key=api_key)
        entries = []
        for model in client.models.list():
            name = str(getattr(model, "name", "") or "").replace("models/", "")
            methods = getattr(model, "supported_generation_methods", None) or []
            # Only show models that can generate content (skip embeddings etc.).
            if name and ("generateContent" in methods or not methods):
                entries.append(name)
    except Exception as exc:
        print(f"Could not list models: {type(exc).__name__}: {exc}")
        print("If your key was rejected, re-copy it from https://aistudio.google.com/.")
        return 1

    if not entries:
        print("  (no models returned - check your key and quota)")
    else:
        for name in sorted(entries):
            print(f"  {name}")

    current = Config.GEMINI_MODEL
    print(f"\nCurrent GEMINI_MODEL: {current}")
    if entries and current not in entries:
        print(f"  WARNING: '{current}' is NOT in the list above!")
        print("  Update GEMINI_MODEL in your .env file to one of the listed models.")

    fallbacks = Config.GEMINI_FALLBACK_MODELS
    print(f"Current GEMINI_FALLBACK_MODELS: {fallbacks}")
    print("\nTip: when the primary model is busy, the app automatically tries the")
    print("fallback models. Set GEMINI_FALLBACK_MODELS in .env to a comma-separated")
    print("list from above (e.g. gemini-3.8-flash-lite) to control that chain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
