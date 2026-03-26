"""Cron-like job scheduler — runs scheduled prompts and delivers via configured channels.

Minimal implementation: checks every 60s if any job's cron expression matches
the current time, runs the agent, and sends the result to Telegram and/or Discord.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from mako.channels.discord import DiscordChannel

from mako.channels.common import split_message

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """A scheduled job definition."""

    name: str
    cron: str  # "minute hour day month weekday"
    tz: str  # e.g. "America/New_York"
    prompt: str
    chat_id: int = 0  # Telegram chat ID to deliver to
    discord_user_id: int = 0  # Discord user ID to deliver to
    enabled: bool = True
    timeout_seconds: int = 300

    # Runtime state (not persisted)
    last_run_minute: tuple[int, ...] = field(default_factory=tuple, repr=False)


def _match_cron_field(field_expr: str, value: int) -> bool:
    """Check if a cron field expression matches a value.

    Supports: * (any), exact number, comma-separated values, ranges (1-5),
    and step values (*/2, 1-5/2).
    """
    if field_expr == "*":
        return True

    for part in field_expr.split(","):
        # Handle step values
        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)

        if part == "*":
            if value % step == 0:
                return True
        elif "-" in part:
            start, end = part.split("-", 1)
            if int(start) <= value <= int(end) and (value - int(start)) % step == 0:
                return True
        else:
            if value == int(part):
                return True

    return False


def _matches_cron(cron_expr: str, tz: str) -> bool:
    """Check if a cron expression matches the current time in the given timezone."""
    from datetime import datetime

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        logger.error("Invalid cron expression: %s", cron_expr)
        return False

    now = datetime.now(ZoneInfo(tz))
    minute, hour, day, month, weekday = parts

    # Standard cron: 0=Sunday, 1=Monday, ..., 6=Saturday
    # Python weekday(): 0=Monday, ..., 6=Sunday
    # Convert Python weekday to cron weekday
    cron_weekday = (now.weekday() + 1) % 7

    return (
        _match_cron_field(minute, now.minute)
        and _match_cron_field(hour, now.hour)
        and _match_cron_field(day, now.day)
        and _match_cron_field(month, now.month)
        and _match_cron_field(weekday, cron_weekday)
    )


def load_jobs(path: Path) -> list[Job]:
    """Load job definitions from a JSON file."""
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        jobs = []
        for j in data.get("jobs", []):
            jobs.append(Job(
                name=j["name"],
                cron=j["cron"],
                tz=j.get("tz", "UTC"),
                prompt=j["prompt"],
                chat_id=int(j.get("chat_id", 0)),
                discord_user_id=int(j.get("discord_user_id", 0)),
                enabled=j.get("enabled", True),
                timeout_seconds=j.get("timeout_seconds", 300),
            ))
        logger.info("Loaded %d job(s) from %s", len(jobs), path)
        return jobs
    except Exception as e:
        logger.error("Failed to load jobs from %s: %s", path, e)
        return []


class Scheduler:
    """Runs scheduled jobs on a 60-second check interval."""

    def __init__(
        self,
        jobs: list[Job],
        agent,
        store,
        telegram_bot=None,
        discord_channel: DiscordChannel | None = None,
    ) -> None:
        self.jobs = [j for j in jobs if j.enabled]
        self.agent = agent
        self.store = store
        self.telegram_bot = telegram_bot
        self.discord_channel = discord_channel
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.jobs:
            logger.info("No scheduled jobs configured")
            return
        logger.info("Scheduler starting with %d job(s): %s",
                     len(self.jobs), ", ".join(j.name for j in self.jobs))
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def _run_loop(self) -> None:
        """Check every 60 seconds if any job should fire."""
        try:
            while True:
                await self._check_jobs()
                # Sleep until the next minute boundary + 1s buffer
                now = time.time()
                sleep_seconds = 61 - (now % 60)
                await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            pass

    async def _check_jobs(self) -> None:
        """Check all jobs and fire any that match the current time."""
        from datetime import datetime

        for job in self.jobs:
            if not _matches_cron(job.cron, job.tz):
                continue

            # Deduplicate: don't fire twice in the same minute
            now = datetime.now(ZoneInfo(job.tz))
            current_minute = (now.year, now.month, now.day, now.hour, now.minute)
            if job.last_run_minute == current_minute:
                continue
            job.last_run_minute = current_minute

            logger.info("Firing job '%s'", job.name)
            asyncio.create_task(self._execute_job(job))

    async def _execute_job(self, job: Job) -> None:
        """Execute a job: run agent and deliver result to configured channels."""
        session_id = self.store.create_session(title=f"Job: {job.name}")

        try:
            response = await asyncio.wait_for(
                self.agent.run(
                    job.prompt,
                    history=[],
                    session_id=f"job_{job.name}",
                ),
                timeout=job.timeout_seconds,
            )

            # Persist
            self.store.save_message(session_id, "user", f"[Scheduled: {job.name}]")
            self.store.save_message(session_id, "assistant", response)

            # Deliver to configured channels
            if job.chat_id and self.telegram_bot:
                await self._send_telegram(job.chat_id, response)
            if job.discord_user_id and self.discord_channel:
                await self._send_discord(job.discord_user_id, response)

            logger.info("Job '%s' completed and delivered (%d chars)", job.name, len(response))

        except asyncio.TimeoutError:
            logger.error("Job '%s' timed out after %ds", job.name, job.timeout_seconds)
            error_msg = f"[Job '{job.name}' timed out after {job.timeout_seconds}s]"
            if job.chat_id and self.telegram_bot:
                await self._send_telegram(job.chat_id, error_msg)
            if job.discord_user_id and self.discord_channel:
                await self._send_discord(job.discord_user_id, error_msg)
        except Exception as e:
            logger.error("Job '%s' failed: %s", job.name, e, exc_info=True)
            error_msg = f"[Job '{job.name}' failed: {type(e).__name__}]"
            if job.chat_id and self.telegram_bot:
                await self._send_telegram(job.chat_id, error_msg)
            if job.discord_user_id and self.discord_channel:
                await self._send_discord(job.discord_user_id, error_msg)

    async def _send_telegram(self, chat_id: int, text: str) -> None:
        """Send a message to a Telegram chat, splitting if needed."""
        try:
            for chunk in split_message(text, 4096):
                await self.telegram_bot.send_message(chat_id=chat_id, text=chunk)
        except Exception as e:
            logger.error("Failed to send Telegram message to %d: %s", chat_id, e)

    async def _send_discord(self, user_id: int, text: str) -> None:
        """Send a DM to a Discord user, splitting if needed."""
        try:
            await self.discord_channel.send_message(user_id, text)
        except Exception as e:
            logger.error("Failed to send Discord message to %d: %s", user_id, e)
