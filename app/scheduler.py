"""In-process scheduler.

Two modes per job:

* ``schedule_times`` — a list of ``"HH:MM"`` wall-clock slots in the panel
  timezone (this is what the admin sees: «ساعت ۸ و ۱۴ و ۲۱»).
* ``interval_minutes`` — run every N minutes instead (0 disables it).

A missed slot is caught up on the next tick because due-ness is computed from
the last successful run, not from an in-memory timer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, db, pipeline

logger = logging.getLogger("rozaneh.scheduler")

STATE: dict = {
    "enabled": config.SCHEDULER_ENABLED,
    "running_job": None,
    "last_tick": "",
    "started_at": "",
}

_task: asyncio.Task | None = None


def panel_tz() -> ZoneInfo:
    name = db.get_setting("timezone") or config.DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def parse_times(raw: str | None) -> list[tuple[int, int]]:
    slots: list[tuple[int, int]] = []
    raw = (raw or "").strip()
    if raw.startswith("["):
        # stored as a JSON array: ["08:00", "20:30"]
        try:
            raw = ",".join(str(x) for x in json.loads(raw))
        except (ValueError, TypeError):
            raw = raw.strip("[]").replace('"', "")
    for chunk in raw.replace("،", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            hh, _, mm = chunk.partition(":")
        elif len(chunk) in (3, 4) and chunk.isdigit():
            hh, mm = chunk[:-2], chunk[-2:]
        else:
            continue
        try:
            hour, minute = int(hh), int(mm)
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            if (hour, minute) not in slots:
                slots.append((hour, minute))
    return sorted(slots)


def _last_run_local(job: dict, tz: ZoneInfo) -> datetime | None:
    raw = job.get("last_run") or ""
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(tz)


def next_run(job: dict, now: datetime | None = None) -> datetime | None:
    if not int(job.get("enabled", 1)):
        return None
    tz = panel_tz()
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    interval = int(job.get("interval_minutes") or 0)
    if interval > 0:
        last = _last_run_local(job, tz)
        if last is None:
            return now
        due = last + timedelta(minutes=interval)
        return due if due > now else now
    slots = parse_times(job.get("schedule_times"))
    if not slots:
        return None
    for add_days in range(0, 8):
        day = (now + timedelta(days=add_days)).date()
        for hour, minute in slots:
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if candidate > now:
                return candidate
    return None


def is_due(job: dict, now: datetime | None = None) -> bool:
    if not int(job.get("enabled", 1)):
        return False
    tz = panel_tz()
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    last_run = _last_run_local(job, tz)
    interval = int(job.get("interval_minutes") or 0)
    if interval > 0:
        return last_run is None or now - last_run >= timedelta(minutes=interval)

    slots = parse_times(job.get("schedule_times"))
    if not slots:
        return False

    # most recent slot that has already passed
    latest: datetime | None = None
    for add_days in (0, 1, 2):
        day = (now - timedelta(days=add_days)).date()
        for hour, minute in slots:
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if candidate <= now and (latest is None or candidate > latest):
                latest = candidate
    if latest is None:
        return False
    return last_run is None or last_run < latest


async def tick() -> None:
    now = datetime.now(timezone.utc)
    STATE["last_tick"] = now.replace(microsecond=0).isoformat()
    jobs = db.query("SELECT * FROM jobs WHERE enabled = 1")
    for job in jobs:
        if not is_due(job, now):
            continue
        STATE["running_job"] = job.get("name") or str(job.get("id"))
        db.log(job["id"], f"⏰ اجرای زمان‌بندی‌شده «{job.get('name')}»")
        try:
            report = await pipeline.run_job(job, force=True)
            if not report.get("ok"):
                db.log(job["id"], f"⚠️ {report.get('error')}", level="warn")
        except Exception as exc:  # noqa: BLE001 - scheduler must never die
            logger.exception("job %s failed", job.get("id"))
            db.log(job["id"], f"💥 خطای غیرمنتظره: {exc}", level="error")
            db.execute(
                "UPDATE jobs SET last_run = ?, last_result = ? WHERE id = ?",
                (db.now_iso(), f"خطا: {exc}"[:200], job["id"]),
            )
        finally:
            STATE["running_job"] = None


async def _loop() -> None:
    STATE["started_at"] = db.now_iso()
    logger.info("scheduler started (tick=%ss)", config.TICK_SECONDS)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed")
        await asyncio.sleep(max(5, config.TICK_SECONDS))


def start() -> None:
    global _task
    if not config.SCHEDULER_ENABLED or _task is not None:
        return
    _task = asyncio.create_task(_loop(), name="newsrail-scheduler")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _task = None
