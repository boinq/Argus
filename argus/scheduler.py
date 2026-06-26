from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from argus.models import IngestResult
from argus.repository import (
    get_scheduler_job_status,
    scheduler_job_paused,
    set_scheduler_job_paused,
    set_scheduler_job_status,
)


IngestJob = Callable[[], IngestResult]


@dataclass
class PollJob:
    id: str
    source_id: str
    name: str
    interval_seconds: int
    handler: IngestJob
    initial_delay_seconds: int = 0
    last_started: datetime | None = None
    last_finished: datetime | None = None
    next_run_at: datetime | None = None
    last_result: str | None = None
    last_error: str | None = None
    running: bool = False
    paused: bool = False
    runs: int = 0
    failures: int = 0


class PollScheduler:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.jobs: dict[str, PollJob] = {}
        self.tasks: list[asyncio.Task[None]] = []
        self.stop_event = asyncio.Event()

    def register(self, job: PollJob) -> None:
        self.jobs[job.id] = job

    def start(self) -> None:
        if not self.enabled:
            return
        self.stop_event.clear()
        startup_delay = startup_delay_seconds()
        stagger = scheduler_stagger_seconds()
        for index, job in enumerate(self.jobs.values()):
            job.initial_delay_seconds = startup_delay + (index * stagger)
        self.tasks = [
            asyncio.create_task(self._run_loop(job), name=f"poll:{job.id}")
            for job in self.jobs.values()
        ]

    async def stop(self) -> None:
        self.stop_event.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

    async def run_once(self, job_id: str) -> IngestResult:
        job = self.jobs[job_id]
        return await self._run_job(job)

    def pause(self, job_id: str) -> PollJob:
        job = self.jobs[job_id]
        job.paused = True
        job.next_run_at = None
        set_scheduler_job_paused(job_id, True)
        self.persist_job_status(job)
        return job

    def resume(self, job_id: str) -> PollJob:
        job = self.jobs[job_id]
        job.paused = False
        set_scheduler_job_paused(job_id, False)
        self.persist_job_status(job)
        return job

    def snapshot(self) -> list[dict[str, object]]:
        return [self.snapshot_job(job) for job in self.jobs.values()]

    def snapshot_job(self, job: PollJob) -> dict[str, object]:
        self.sync_job_control(job)
        status = {
            "id": job.id,
            "source_id": job.source_id,
            "name": job.name,
            "interval_seconds": job.interval_seconds,
            "enabled": self.enabled,
            "running": job.running,
            "paused": job.paused,
            "runs": job.runs,
            "failures": job.failures,
            "last_started": job.last_started,
            "last_finished": job.last_finished,
            "next_run_at": job.next_run_at,
            "last_result": job.last_result,
            "last_error": job.last_error,
        }
        stored = get_scheduler_job_status(job.id)
        if stored:
            status.update(stored)
        if job.paused:
            status["next_run_at"] = None
            status["running"] = False
        return status

    async def _run_loop(self, job: PollJob) -> None:
        await self._sleep_until_next_run(job, job.initial_delay_seconds)
        while not self.stop_event.is_set():
            await self._wait_if_paused(job)
            if self.stop_event.is_set():
                break
            job.next_run_at = None
            await self._run_scheduled_job(job)
            await self._sleep_until_next_run(job, job.interval_seconds)

    async def _run_scheduled_job(self, job: PollJob) -> IngestResult | None:
        try:
            return await self._run_job(job)
        except Exception:
            # Keep one source failure from killing its polling loop.
            return None

    async def _run_job(self, job: PollJob) -> IngestResult:
        if job.running:
            return IngestResult(
                source_id=job.source_id,
                observations_seen=0,
                observations_stored=0,
                events_created=0,
                events_updated=0,
                message=f"{job.name} is already running.",
            )

        job.running = True
        job.last_started = datetime.now(timezone.utc)
        self.persist_job_status(job)
        try:
            result = await asyncio.to_thread(job.handler)
            job.runs += 1
            job.last_result = result.message
            job.last_error = None
            return result
        except Exception as error:
            job.failures += 1
            job.last_error = str(error)
            raise
        finally:
            job.running = False
            job.last_finished = datetime.now(timezone.utc)
            self.persist_job_status(job)

    async def _wait_if_paused(self, job: PollJob) -> None:
        self.sync_job_control(job)
        while job.paused and not self.stop_event.is_set():
            job.next_run_at = None
            self.persist_job_status(job)
            await self._sleep_or_stop(1)
            self.sync_job_control(job)

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except TimeoutError:
            return

    async def _sleep_until_next_run(self, job: PollJob, seconds: int) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        job.next_run_at = deadline
        self.persist_job_status(job)
        while not self.stop_event.is_set():
            self.sync_job_control(job)
            if job.paused:
                job.next_run_at = None
                self.persist_job_status(job)
                return
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return
            await self._sleep_or_stop(min(remaining, 1))

    def sync_job_control(self, job: PollJob) -> None:
        job.paused = scheduler_job_paused(job.id)

    def persist_job_status(self, job: PollJob) -> None:
        set_scheduler_job_status(
            job_id=job.id,
            running=job.running,
            runs=job.runs,
            failures=job.failures,
            last_started=job.last_started,
            last_finished=job.last_finished,
            next_run_at=job.next_run_at,
            last_result=job.last_result,
            last_error=job.last_error,
        )


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def startup_delay_seconds() -> int:
    return max(0, env_int("ARGUS_SCHEDULER_STARTUP_DELAY_SECONDS", 15))


def scheduler_stagger_seconds() -> int:
    return max(0, env_int("ARGUS_SCHEDULER_STAGGER_SECONDS", 30))
