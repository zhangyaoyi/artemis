# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Task Scheduler: CRUD over APScheduler jobs that run a Recommended Task
preset once or on a cron schedule.

APScheduler's `SQLAlchemyJobStore` is the system of record for a schedule's
trigger definition, next-run time, and paused state -- this module does not
maintain its own table for any of that. The only custom persistence is
`schedule_status_repository`, which tracks the last run's outcome (a field
APScheduler's job store has no place for).
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from artemis.config import DB_PATH

try:
    from admin_console.database.repositories.schedule_status_repository import (
        schedule_status_repository,
    )
    from admin_console.database.repositories.task_preset_repository import (
        task_preset_repository,
    )
    from admin_console.services.task_queue_service import task_queue_service
except ImportError:
    from apps.admin_console.database.repositories.schedule_status_repository import (
        schedule_status_repository,
    )
    from apps.admin_console.database.repositories.task_preset_repository import (
        task_preset_repository,
    )
    from apps.admin_console.services.task_queue_service import task_queue_service

logger = logging.getLogger(__name__)


async def run_scheduled_task(preset_id: str, schedule_id: str) -> None:
    """APScheduler job callback -- fired at the schedule's due time.

    Must stay a top-level, importable function: `SQLAlchemyJobStore` pickles
    a *reference* to this function (module path + name), not a closure, so
    it cannot be a bound method or a lambda. It reads the preset and the
    other singletons below as module globals rather than through a service
    instance for the same reason -- so tests can `monkeypatch.setattr` them
    on this module.
    """
    preset = task_preset_repository.get(preset_id)
    if preset is None:
        schedule_status_repository.set(
            schedule_id, datetime.now().isoformat(), "error: preset deleted"
        )
        try:
            task_scheduler_service.scheduler.remove_job(schedule_id)
        except JobLookupError:
            pass
        return

    await task_queue_service.enqueue_tasks([preset["goal"]], profile=preset["profile"])
    schedule_status_repository.set(schedule_id, datetime.now().isoformat(), "queued")


def _build_trigger(schedule_type: str, run_at: str | None, cron_expression: str | None) -> Any:
    """Validates schedule fields and returns the APScheduler trigger.

    Raises `ValueError` on any invalid input -- callers map that to a 422.
    """
    if schedule_type == "once":
        if not run_at:
            raise ValueError("run_at is required for schedule_type 'once'.")
        try:
            run_date = datetime.fromisoformat(run_at)
        except ValueError as exc:
            raise ValueError(f"Invalid run_at datetime: {run_at!r}") from exc
        # `DateTrigger` localizes a naive run_date to the scheduler's
        # timezone, so a `run_at` read back off an existing job (and edited)
        # arrives here *aware*. Comparing an aware and a naive datetime
        # raises TypeError -- which the router does not map to a 422 --
        # so pick a `now` that matches whichever form we were given.
        now = datetime.now(run_date.tzinfo) if run_date.tzinfo is not None else datetime.now()
        if run_date <= now:
            raise ValueError("run_at must be in the future.")
        return DateTrigger(run_date=run_date)
    if schedule_type == "cron":
        if not cron_expression:
            raise ValueError("cron_expression is required for schedule_type 'cron'.")
        try:
            trigger = CronTrigger.from_crontab(cron_expression)
        except ValueError as exc:
            raise ValueError(f"Invalid cron expression: {cron_expression!r}") from exc
        return trigger
    raise ValueError(f"Unknown schedule_type: {schedule_type!r}")


def _crontab_from_trigger(trigger: CronTrigger) -> str:
    """Reconstructs the 5-field crontab string from a `CronTrigger`'s fields.

    APScheduler validates a job's `kwargs` against the *target callable's*
    signature (`run_scheduled_task(preset_id, schedule_id)`), so
    `cron_expression` cannot be smuggled through as an extra job kwarg the
    way an earlier draft of this module assumed -- `add_job()` raises
    `ValueError: The target callable does not accept the following keyword
    arguments: cron_expression`. `CronTrigger.fields` exposes the same
    values the trigger was parsed from, so the crontab string is
    recomputed from those instead of being round-tripped through job
    storage.
    """
    fields = {f.name: str(f) for f in trigger.fields}
    return f"{fields['minute']} {fields['hour']} {fields['day']} {fields['month']} {fields['day_of_week']}"


class TaskSchedulerService:
    """Wraps an `AsyncIOScheduler` and maps schedule CRUD onto its jobs API."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        # Built lazily in start(), not here: APScheduler binds to the
        # running asyncio event loop at construction time, and this service
        # is instantiated as a module-level singleton at import time --
        # before uvicorn's event loop exists.
        self.scheduler: AsyncIOScheduler | None = None
        # Set only when start() falls back to a loop it created itself
        # (see start()); shutdown() then owns closing it.
        self._owned_event_loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self.scheduler is not None:
            return
        try:
            event_loop = asyncio.get_running_loop()
        except RuntimeError:
            # `AsyncIOScheduler.start()` unconditionally calls
            # `asyncio.get_running_loop()` when it has no event loop
            # configured yet, which raises here if `start()` runs outside
            # a running loop -- e.g. from a synchronous test fixture, or
            # if this is ever called before uvicorn's loop starts. Passing
            # a loop explicitly at construction sidesteps that: the loop
            # only needs to exist for job-store CRUD (add/get/modify/
            # remove) to work, not to be running. We own this loop (nothing
            # else will ever run or close it), so track it for shutdown().
            event_loop = asyncio.new_event_loop()
            self._owned_event_loop = event_loop
            logger.warning(
                "TaskSchedulerService.start() called outside a running event loop; "
                "scheduled jobs will be added but their triggers will not fire."
            )
        self.scheduler = AsyncIOScheduler(
            event_loop=event_loop,
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{self.db_path}")},
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        if self._owned_event_loop is not None:
            self._owned_event_loop.close()
            self._owned_event_loop = None

    def _serialize_job(self, job) -> dict[str, Any]:
        preset_id = job.args[0]
        preset = task_preset_repository.get(preset_id)
        status = schedule_status_repository.get(job.id)
        is_cron = isinstance(job.trigger, CronTrigger)
        return {
            "id": job.id,
            "preset_id": preset_id,
            "preset_title": preset["title"] if preset else "(preset deleted)",
            "schedule_type": "cron" if is_cron else "once",
            # Emitted in the exact shape `<input type="datetime-local">`
            # accepts: no UTC offset, no microseconds. `.isoformat()` would
            # include both (DateTrigger localizes its run_date), and the
            # HTML spec makes such an input render *blank* rather than
            # error -- while the value still round-trips back on save.
            "run_at": None if is_cron else job.trigger.run_date.strftime("%Y-%m-%dT%H:%M"),
            "cron_expression": _crontab_from_trigger(job.trigger) if is_cron else None,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "paused": job.next_run_time is None,
            "last_run_at": status["last_run_at"] if status else None,
            "last_status": status["last_status"] if status else None,
        }

    def create_schedule(
        self,
        preset_id: str,
        schedule_type: str,
        run_at: str | None = None,
        cron_expression: str | None = None,
    ) -> dict[str, Any] | None:
        if task_preset_repository.get(preset_id) is None:
            return None
        trigger = _build_trigger(schedule_type, run_at, cron_expression)
        schedule_id = f"sched_{uuid4().hex}"
        job = self.scheduler.add_job(
            run_scheduled_task,
            trigger=trigger,
            args=[preset_id, schedule_id],
            id=schedule_id,
            misfire_grace_time=300,
            coalesce=True,
        )
        return self._serialize_job(job)

    def list_schedules(self) -> list[dict[str, Any]]:
        return [self._serialize_job(job) for job in self.scheduler.get_jobs()]

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        job = self.scheduler.get_job(schedule_id)
        return self._serialize_job(job) if job else None

    def update_schedule(
        self,
        schedule_id: str,
        preset_id: str,
        schedule_type: str,
        run_at: str | None = None,
        cron_expression: str | None = None,
    ) -> dict[str, Any] | None:
        job = self.scheduler.get_job(schedule_id)
        if job is None:
            return None
        if task_preset_repository.get(preset_id) is None:
            return None
        trigger = _build_trigger(schedule_type, run_at, cron_expression)
        self.scheduler.modify_job(schedule_id, args=[preset_id, schedule_id])
        # modify_job() alone would leave next_run_time stale for the old
        # trigger; reschedule_job() recomputes it against the new one.
        self.scheduler.reschedule_job(schedule_id, trigger=trigger)
        return self._serialize_job(self.scheduler.get_job(schedule_id))

    def delete_schedule(self, schedule_id: str) -> bool:
        job = self.scheduler.get_job(schedule_id)
        if job is None:
            return False
        self.scheduler.remove_job(schedule_id)
        schedule_status_repository.delete(schedule_id)
        return True

    def pause_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        job = self.scheduler.get_job(schedule_id)
        if job is None:
            return None
        if isinstance(job.trigger, DateTrigger):
            raise ValueError("Cannot pause a one-time ('once') schedule.")
        self.scheduler.pause_job(schedule_id)
        return self._serialize_job(self.scheduler.get_job(schedule_id))

    def resume_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        job = self.scheduler.get_job(schedule_id)
        if job is None:
            return None
        if isinstance(job.trigger, DateTrigger):
            raise ValueError("Cannot resume a one-time ('once') schedule.")
        self.scheduler.resume_job(schedule_id)
        return self._serialize_job(self.scheduler.get_job(schedule_id))


task_scheduler_service = TaskSchedulerService()
