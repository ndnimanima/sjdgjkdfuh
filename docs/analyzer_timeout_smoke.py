"""Offline Analyzer timeout, chunking, response-shape, and diagnostics smoke test.

Run from the repository root with ``python docs/analyzer_timeout_smoke.py``.
All model calls are mocked; no external endpoint or real credential is used.
"""
from __future__ import annotations

import asyncio
import json
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
    from app import analyzer, db

    calls: list[dict] = []
    response_body = {"choices": [{"message": {"content": "A sufficiently long response from the mocked model."}}]}
    hanging = {"value": False}

    class FakeResponse:
        status_code = 200

        def json(self):
            return response_body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            calls.append({"url": url, "payload": json, "headers": headers, "timeout": self.timeout})
            if hanging["value"]:
                await asyncio.Event().wait()
            return FakeResponse()

    original_client = analyzer.httpx.AsyncClient
    original_update = analyzer._update_analysis
    progress: list[str] = []
    analyzer.httpx.AsyncClient = FakeClient
    analyzer._update_analysis = lambda _aid, **fields: progress.append(str(fields.get("progress_msg", "")))
    try:
        output = await analyzer._llm_chat(
            "https://example.invalid/v1", "offline-smoke-model", "mocked-only-key",
            "system", "user", timeout=9,
        )
        check("chat request caps output tokens and passes a hard timeout",
              output.startswith("A sufficiently")
              and calls[-1]["payload"].get("max_tokens") == 1800
              and calls[-1]["timeout"] == 9)
        check("chat request uses a bearer credential without returning it",
              calls[-1]["headers"].get("Authorization") == "Bearer mocked-only-key"
              and "mocked-only-key" not in output)

        response_body["choices"] = [{"message": {"content": [{"type": "text", "text": "First part"}, {"text": "Second part"}]}}]
        list_content = await analyzer._llm_chat("https://example.invalid/v1", "m", "fake", "s", "u")
        check("normalizes list-of-text OpenAI-compatible response shapes", list_content == "First part\nSecond part")

        response_body["choices"] = [{"text": "Legacy completion text"}]
        legacy_text = await analyzer._llm_chat("https://example.invalid/v1", "m", "fake", "s", "u")
        check("accepts a legacy choice.text response", legacy_text == "Legacy completion text")

        response_body["choices"] = [{"message": {"content": "   "}}]
        try:
            await analyzer._llm_chat("https://example.invalid/v1", "m", "fake", "s", "u")
            raise AssertionError("empty responses should fail")
        except RuntimeError as exc:
            check("empty model output has a named, nonblank failure", str(exc) == "analysis_api_empty_response")

        hanging["value"] = True
        try:
            await analyzer._llm_chat("https://example.invalid/v1", "m", "fake", "s", "u", timeout=1)
            raise AssertionError("hung requests should time out")
        except asyncio.TimeoutError:
            check("hung model request is cancelled by the per-call timeout", True)
        finally:
            hanging["value"] = False

        long_text = "A" * 18000 + "MARKER-ONE" + "B" * 18000 + "MARKER-TWO" + "C" * 18000 + "MARKER-THREE" + "D" * 18000
        text_chunks = analyzer._build_timed_chunks({"text": long_text}, max_chunk_chars=10000, max_chunks=4)
        check("large plain-text sources are covered by at most four bounded chunks",
              len(text_chunks) == 4 and all(len(text) <= 10003 for _, text in text_chunks)
              and all(label for label, _ in text_chunks))

        concurrent = {"active": 0, "maximum": 0, "calls": 0}

        async def fake_chunked_llm(base_url, model, api_key, system, user, timeout=40.0):
            concurrent["active"] += 1
            concurrent["maximum"] = max(concurrent["maximum"], concurrent["active"])
            concurrent["calls"] += 1
            await asyncio.sleep(0.01)
            concurrent["active"] -= 1
            if "expert Persian content analyst" in system:
                return "• نکتهٔ بخش"
            return json.dumps({
                "title_fa": "عنوان آزمایشی",
                "summary": "خلاصهٔ آزمایشیِ کافی برای بررسی ساختار پاسخ و ثبت نتیجه.",
                "key_points": ["نکتهٔ نخست"],
                "deep_analysis": "تحلیل آزمایشی",
                "timeline": [],
                "channel_draft": "پیش‌نویس آزمایشی",
            }, ensure_ascii=False)

        original_llm_chat = analyzer._llm_chat
        analyzer._llm_chat = fake_chunked_llm
        timed_data = {
            "title": "آزمون بخش‌بندی",
            "platform": "youtube",
            "duration_sec": 7200,
            "text": "متن آزمایشی",
            "segments": [
                {"start": 0, "text": "بخش اول " * 20},
                {"start": 1800, "text": "بخش دوم " * 20},
                {"start": 3600, "text": "بخش سوم " * 20},
                {"start": 5400, "text": "بخش چهارم " * 20},
            ],
        }
        result = await analyzer._analyze_with_llm(1, timed_data, ("https://example.invalid/v1", "m", "fake"))
        check("hierarchical analysis emits final JSON and keeps chunk concurrency bounded",
              result["summary"].startswith("خلاصه") and concurrent["calls"] == 5
              and concurrent["maximum"] <= 2
              and any("1 تا 2 از 4" in item for item in progress)
              and any("3 تا 4 از 4" in item for item in progress))
        analyzer._llm_chat = original_llm_chat

        plain_answer = analyzer._parse_llm_analysis(
            "این یک پاسخ متنی کافی و قابل استفاده است که مدل بدون قالب JSON برگردانده است. بنابراین محتوا نباید خالی بماند.",
            {"title": "عنوان منبع"},
        )
        check("non-JSON text response is retained as a useful fallback summary", bool(plain_answer["summary"]))
        check("provider and overall timeout errors are useful and key-safe",
              "کافی نیست" in analyzer._analysis_error_detail(RuntimeError("llm_http_402"))
              and "مهلت کلی" in analyzer._analysis_error_detail(RuntimeError("analysis_overall_timeout"))
              and "مدل" in analyzer._analysis_error_detail(RuntimeError("analysis_api_empty_response")))

        analyzer._update_analysis = original_update
        analyzer.extract_any_url = lambda *args, **kwargs: asyncio.sleep(0, result={
            "title": "عنوان تست", "text": "این یک متن آزمایشی به اندازه کافی بلند برای اجرای تست کلی است.",
            "platform": "web", "segments": [], "duration_sec": 0,
        })
        analyzer._active_llm = lambda: ("https://example.invalid/v1", "slow-model", "fake")
        analyzer._analyze_with_llm = lambda *args, **kwargs: asyncio.sleep(5)
        analyzer.LLM_ANALYSIS_TIMEOUT = 0.03
        aid = db.execute(
            "INSERT INTO analyses(url, platform, status, created_at) VALUES(?,?,?,?)",
            ("https://example.invalid/test", "web", "processing", db.now_iso()),
        )
        total_timeout_result = await analyzer.run_analysis_task(aid, "https://example.invalid/test")
        check("overall model-analysis deadline marks the job failed with a clear message",
              total_timeout_result.get("status") == "failed"
              and "مهلت کلی تحلیل" in total_timeout_result.get("error", ""))

    finally:
        analyzer.httpx.AsyncClient = original_client
        analyzer._update_analysis = original_update
        if "original_llm_chat" in locals():
            analyzer._llm_chat = original_llm_chat


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rozaneh-analyzer-timeout-smoke-") as tmp:
        os.environ.update(
            DATA_DIR=tmp,
            ADMIN_PASSWORD="rozaneh-analyzer-smoke-password",
            COOKIE_SECURE="0",
            SCHEDULER_ENABLED="0",
            DEFAULT_TZ="UTC",
        )
        asyncio.run(exercise())
    print("Analyzer timeout and response handling smoke test passed.")


if __name__ == "__main__":
    main()
