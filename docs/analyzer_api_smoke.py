"""Offline model-discovery smoke tests for OpenAI-compatible analysis APIs.

Run from the repository root with ``python docs/analyzer_api_smoke.py``.
All HTTP requests are mocked; no external endpoint or real credential is used.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("  ok  ", label)


async def exercise() -> None:
    from app import analyzer

    calls: list[tuple[str, dict[str, str]]] = []
    response_status = {"value": 200}

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

        def json(self):
            if self.status_code == 200:
                return {"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-flash"}, {"name": "missing-id"}]}
            return {"error": {"message": "private provider response"}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *, headers):
            calls.append((url, headers))
            return FakeResponse(response_status["value"])

    original_client = analyzer.httpx.AsyncClient
    analyzer.httpx.AsyncClient = FakeClient
    try:
        listed = await analyzer.fetch_api_models("https://api.deepseek.com/", "smoke-only-secret")
        check("uses the OpenAI-compatible /models endpoint and bearer authorization", bool(calls)
              and calls[-1][0] == "https://api.deepseek.com/models"
              and calls[-1][1].get("Authorization") == "Bearer smoke-only-secret")
        check("returns only valid model ids in stable order", listed == {
            "ok": True, "models": ["deepseek-flash", "deepseek-v4-pro"]
        })
        check("does not echo API credentials", "smoke-only-secret" not in str(listed))

        response_status["value"] = 402
        balance = await analyzer.fetch_api_models("https://api.deepseek.com", "smoke-only-secret")
        check("maps HTTP 402 without leaking the provider response body", balance == {
            "ok": False, "error": "models_http_402"
        } and "private provider response" not in str(balance))
    finally:
        analyzer.httpx.AsyncClient = original_client


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-model-discovery-smoke-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-model-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
        )
        asyncio.run(exercise())
    print("Analyzer API model-discovery smoke test passed.")


if __name__ == "__main__":
    main()
