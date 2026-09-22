# Task Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users schedule an existing Recommended Task preset to run automatically — once at a specific time, or repeatedly on a cron expression — with full CRUD from a new UI page, and have persistence of the schedule itself delegated to APScheduler instead of a hand-rolled table + poll loop.

**Architecture:** A new `TaskSchedulerService` wraps an `AsyncIOScheduler` (APScheduler) configured with a `SQLAlchemyJobStore` pointed at the app's existing sqlite file — APScheduler's own `apscheduler_jobs` table is the system of record for trigger definitions, next-run time, and paused state. The only custom persistence is a tiny `schedule_run_status` side table (via a new `ScheduleStatusRepository`) tracking each schedule's last-run outcome, since the job store has no field for that. A new `schedules.py` router exposes CRUD + pause/resume over `/api/schedules`, mapping directly onto APScheduler's `add_job`/`get_jobs`/`modify_job`/`reschedule_job`/`remove_job`/`pause_job`/`resume_job`. At fire time, a top-level `run_scheduled_task(preset_id, schedule_id)` function (must stay top-level and importable — the job store pickles a reference to it, not a closure) re-reads the preset and calls the existing `task_queue_service.enqueue_tasks(...)`, the same queueing call a manual "Run" ultimately reaches. The frontend gets a new `/schedules` page (its own nav tab, not bolted onto the already-large `home.component.html`), a `ScheduleFormComponent` modal, and a `ScheduleService`, all following the exact same shape as the existing App Registry / Recommended Tasks CRUD features.

**Tech Stack:** FastAPI + Pydantic + sqlite3 + APScheduler 3.x (`AsyncIOScheduler`, `SQLAlchemyJobStore`) + SQLAlchemy (backend, `apps/admin_console`), Angular 22 standalone components + signals + `HttpClient` (frontend, `apps/showcase_ui`), pytest (`pytest-asyncio` for router/service tests). `ng test` may not be able to launch headless Chrome in the sandbox this plan is executed in (confirmed unusable in the two prior CRUD features built the same way) — if that's still true when you reach a frontend task, follow the same adaptation used there: `cd apps/showcase_ui && npx ng build` as the compile-check gate, plus a rigorous manual trace of each spec's assertions against the component code, called out explicitly in your task report.

**Spec:** `docs/superpowers/specs/2026-09-23-task-scheduler-design.md`

## Global Constraints

- APScheduler's `SQLAlchemyJobStore` is the single source of truth for a schedule's trigger (cron expression / run-at time), next-run time, and paused state. No custom table duplicates any of that — the only new table is `schedule_run_status` (last-run outcome only).
- The APScheduler job callback (`run_scheduled_task`) must be a top-level, importable module function — never a bound method, lambda, or closure — because `SQLAlchemyJobStore` pickles a reference to it, not its captured state. It reads its dependencies (`task_preset_repository`, `task_queue_service`, `schedule_status_repository`, `task_scheduler_service`) as module globals in `task_scheduler_service.py` for the same reason, so tests can `monkeypatch.setattr` them there.
- Two schedule types only: `once` (a specific datetime) and `cron` (a raw cron expression string). No day-of-week checkboxes, no cron builder UI.
- A scheduled run is submitted via `task_queue_service.enqueue_tasks(...)` directly — not through `/api/run`'s device-readiness/lock-state checks, which assume an interactive user able to unlock a phone. This was an explicit scope decision, not an oversight.
- Only the most recent run's timestamp and status are kept per schedule. No history log.
- Pause/resume applies only to `cron` schedules; a `once` schedule can only be deleted (API returns 400 on pause/resume of a `once` schedule).
- Every new `.py` and `.ts` file gets the same Apache 2.0 license header already used throughout the codebase (see any existing file in `apps/admin_console` or `apps/showcase_ui/src/app` for the exact text) — copy it verbatim into every new file below; it is omitted from the code blocks in this plan purely for readability.
- New backend modules that import sibling `admin_console` modules use the existing dual-path `try: from admin_console.x import y / except ImportError: from apps.admin_console.x import y` pattern, exactly like every existing file in `apps/admin_console`.

---

### Task 1: `TaskPresetRepository.get()`

**Files:**
- Modify: `apps/admin_console/database/repositories/task_preset_repository.py`
- Modify: `tests/unit/admin_console/test_task_preset_repository.py`

**Interfaces:**
- Consumes: nothing new — same `db_session`/`_decode_row` already in the file.
- Produces: `TaskPresetRepository.get(preset_id: str) -> dict[str, Any] | None`. Task 3 (`TaskSchedulerService`) consumes this to validate a `preset_id` exists and to look up a preset's `goal`/`profile`/`title` at fire time and at API-serialization time.

- [ ] **Step 1: Write the failing test**

Add this to the end of `tests/unit/admin_console/test_task_preset_repository.py` (after the existing tests — do not remove anything already there):

```python
def test_get_returns_none_for_missing_id(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    assert repo.get("does-not-exist") is None


def test_get_returns_existing_row(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    repo.create(_row())

    row = repo.get("task-1")

    assert row["title"] == "Test Task"
    assert row["apps"] == [
        {"name": "Test App", "icon": "star", "pkg": "com.test.app", "category": "tools"}
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_repository.py -v`
Expected: FAIL with `AttributeError: 'TaskPresetRepository' object has no attribute 'get'`

- [ ] **Step 3: Implement `get()`**

In `apps/admin_console/database/repositories/task_preset_repository.py`, add this method to `TaskPresetRepository` (placed right after `list_all`, before `create`):

```python
    def get(self, preset_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            row = conn.execute(
                "SELECT * FROM task_presets WHERE id = ?", (preset_id,)
            ).fetchone()
        return self._decode_row(row) if row else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_repository.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add apps/admin_console/database/repositories/task_preset_repository.py tests/unit/admin_console/test_task_preset_repository.py
git commit -m "feat: add TaskPresetRepository.get() for single-row lookup"
```

---

### Task 2: `ScheduleStatusRepository`

**Files:**
- Create: `apps/admin_console/database/repositories/schedule_status_repository.py`
- Test: `tests/unit/admin_console/test_schedule_status_repository.py`

**Interfaces:**
- Consumes: `apps.admin_console.database.connection.db_session(db_path)` (existing context manager, same one `TaskPresetRepository` uses).
- Produces: `ScheduleStatusRepository` with `get(job_id: str) -> dict | None` (keys: `job_id`, `last_run_at`, `last_status`), `set(job_id: str, last_run_at: str, last_status: str) -> None` (insert-or-replace), `delete(job_id: str) -> None` (no-op if missing); and the module-level singleton `schedule_status_repository = ScheduleStatusRepository()`. Task 3 consumes all three methods.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_schedule_status_repository.py`:

```python
from apps.admin_console.database.repositories.schedule_status_repository import (
    ScheduleStatusRepository,
)


def test_get_returns_none_for_missing_job_id(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    assert repo.get("does-not-exist") is None


def test_set_then_get_round_trips(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.set("sched-1", "2026-09-23T09:00:00", "queued")

    row = repo.get("sched-1")

    assert row["last_run_at"] == "2026-09-23T09:00:00"
    assert row["last_status"] == "queued"


def test_set_overwrites_existing_row(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.set("sched-1", "2026-09-23T09:00:00", "queued")

    repo.set("sched-1", "2026-09-24T09:00:00", "error: preset deleted")

    row = repo.get("sched-1")
    assert row["last_run_at"] == "2026-09-24T09:00:00"
    assert row["last_status"] == "error: preset deleted"


def test_delete_removes_row(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.set("sched-1", "2026-09-23T09:00:00", "queued")

    repo.delete("sched-1")

    assert repo.get("sched-1") is None


def test_delete_missing_job_id_is_a_no_op(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.delete("does-not-exist")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_schedule_status_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.admin_console.database.repositories.schedule_status_repository'`

- [ ] **Step 3: Implement `ScheduleStatusRepository`**

Create `apps/admin_console/database/repositories/schedule_status_repository.py`:

```python
"""SQLite-backed store for a Task Scheduler schedule's last-run outcome.

This is deliberately the only custom persistence the Task Scheduler feature
owns. A schedule's trigger definition (cron expression / run-at time, next
run time, paused state) lives entirely inside APScheduler's own
`apscheduler_jobs` table -- see `task_scheduler_service.py`.
"""

import sqlite3
from typing import Any

try:
    from admin_console.database.connection import db_session
except ImportError:
    from apps.admin_console.database.connection import db_session


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schedule_run_status (
    job_id TEXT PRIMARY KEY,
    last_run_at TEXT NOT NULL,
    last_status TEXT NOT NULL
)
"""


class ScheduleStatusRepository:
    """Repository for the last-run outcome of a Task Scheduler job."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_TABLE_SQL)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            row = conn.execute(
                "SELECT * FROM schedule_run_status WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def set(self, job_id: str, last_run_at: str, last_status: str) -> None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            conn.execute(
                """
                INSERT INTO schedule_run_status (job_id, last_run_at, last_status)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    last_run_at = excluded.last_run_at,
                    last_status = excluded.last_status
                """,
                (job_id, last_run_at, last_status),
            )
            conn.commit()

    def delete(self, job_id: str) -> None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            conn.execute("DELETE FROM schedule_run_status WHERE job_id = ?", (job_id,))
            conn.commit()


schedule_status_repository = ScheduleStatusRepository()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_schedule_status_repository.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/admin_console/database/repositories/schedule_status_repository.py tests/unit/admin_console/test_schedule_status_repository.py
git commit -m "feat: add ScheduleStatusRepository for last-run outcome tracking"
```

---

### Task 3: `TaskSchedulerService` (APScheduler integration)

**Files:**
- Create: `apps/admin_console/services/task_scheduler_service.py`
- Test: `tests/unit/admin_console/test_task_scheduler_service.py`
- Modify: `pyproject.toml` (new dependencies, via `uv add`)

**Interfaces:**
- Consumes: `task_preset_repository.get(preset_id)` (Task 1), `schedule_status_repository.get/set/delete` (Task 2), `task_queue_service.enqueue_tasks(goals: list[str], profile: str) -> dict` (existing, classmethod-backed singleton).
- Produces: module-level `async def run_scheduled_task(preset_id: str, schedule_id: str) -> None` (the APScheduler job callback), and `TaskSchedulerService` with `start() -> None`, `shutdown() -> None`, `create_schedule(preset_id: str, schedule_type: str, run_at: str | None = None, cron_expression: str | None = None) -> dict | None` (`None` = unknown `preset_id`; raises `ValueError` on invalid cron/run_at — both map to HTTP errors in Task 4), `list_schedules() -> list[dict]`, `get_schedule(schedule_id: str) -> dict | None`, `update_schedule(schedule_id: str, preset_id: str, schedule_type: str, run_at: str | None = None, cron_expression: str | None = None) -> dict | None` (`None` if `schedule_id` or the new `preset_id` doesn't exist), `delete_schedule(schedule_id: str) -> bool`, `pause_schedule(schedule_id: str) -> dict | None` (raises `ValueError` if the job is `once`-type), `resume_schedule(schedule_id: str) -> dict | None` (same restriction); and the module-level singleton `task_scheduler_service = TaskSchedulerService()`. Every returned dict has keys: `id, preset_id, preset_title, schedule_type, run_at, cron_expression, next_run_time, paused, last_run_at, last_status`. Task 4 (the router) consumes every method listed above.

- [ ] **Step 1: Add the new dependencies**

```bash
uv add "apscheduler>=3.10.4,<4.0.0"
uv add "sqlalchemy>=2.0.0"
```

This updates `pyproject.toml` and `uv.lock` and installs both into `.venv`. Verify:

```bash
uv run python -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/admin_console/test_task_scheduler_service.py`:

```python
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.admin_console.database.repositories.schedule_status_repository import (
    ScheduleStatusRepository,
)
from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.services import task_scheduler_service as scheduler_module
from apps.admin_console.services.task_scheduler_service import TaskSchedulerService


def _preset_row(preset_id="preset-1", **overrides):
    row = {
        "id": preset_id,
        "title": "Test Preset",
        "description": "d",
        "goal": "Do the thing",
        "profile": "flash",
        "category": "flash",
        "tag": "Test",
        "apps": [],
        "required_packages": [],
        "match_mode": "any",
        "priority": 60,
        "is_builtin": False,
        "created_at": "2026-09-23T00:00:00+00:00",
        "updated_at": "2026-09-23T00:00:00+00:00",
    }
    row.update(overrides)
    return row


class _FakeTaskQueueService:
    def __init__(self):
        self.calls = []

    async def enqueue_tasks(self, goals, profile="flash", **kwargs):
        self.calls.append({"goals": goals, "profile": profile})
        return {"status": "queued"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    preset_repo = TaskPresetRepository(tmp_path / "presets.db")
    preset_repo.create(_preset_row("preset-1", title="Test Preset"))
    preset_repo.create(_preset_row("preset-2", title="Other Preset"))
    status_repo = ScheduleStatusRepository(tmp_path / "status.db")
    fake_queue = _FakeTaskQueueService()

    monkeypatch.setattr(scheduler_module, "task_preset_repository", preset_repo)
    monkeypatch.setattr(scheduler_module, "schedule_status_repository", status_repo)
    monkeypatch.setattr(scheduler_module, "task_queue_service", fake_queue)

    svc = TaskSchedulerService(db_path=tmp_path / "jobs.db")
    monkeypatch.setattr(scheduler_module, "task_scheduler_service", svc)
    svc.start()
    yield SimpleNamespace(service=svc, preset_repo=preset_repo, status_repo=status_repo, queue=fake_queue)
    svc.shutdown()


def test_create_schedule_cron_returns_serialized_job(env):
    result = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * 1,3,5")

    assert result["schedule_type"] == "cron"
    assert result["cron_expression"] == "0 9 * * 1,3,5"
    assert result["preset_title"] == "Test Preset"
    assert result["next_run_time"] is not None
    assert result["paused"] is False


def test_create_schedule_once_returns_serialized_job(env):
    run_at = (datetime.now() + timedelta(days=1)).isoformat()

    result = env.service.create_schedule("preset-1", "once", run_at=run_at)

    assert result["schedule_type"] == "once"
    assert result["run_at"] is not None
    assert result["cron_expression"] is None


def test_create_schedule_returns_none_for_unknown_preset(env):
    assert env.service.create_schedule("does-not-exist", "cron", cron_expression="0 9 * * *") is None


def test_create_schedule_rejects_bad_cron_expression(env):
    with pytest.raises(ValueError):
        env.service.create_schedule("preset-1", "cron", cron_expression="not a cron")


def test_create_schedule_rejects_past_run_at(env):
    past = (datetime.now() - timedelta(days=1)).isoformat()

    with pytest.raises(ValueError):
        env.service.create_schedule("preset-1", "once", run_at=past)


def test_list_schedules_returns_all_created(env):
    env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")
    env.service.create_schedule("preset-1", "cron", cron_expression="0 18 * * *")

    assert len(env.service.list_schedules()) == 2


def test_get_schedule_returns_none_for_missing_id(env):
    assert env.service.get_schedule("does-not-exist") is None


def test_update_schedule_changes_preset_and_trigger(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")

    updated = env.service.update_schedule(created["id"], "preset-2", "cron", cron_expression="0 18 * * *")

    assert updated["preset_id"] == "preset-2"
    assert updated["preset_title"] == "Other Preset"
    assert updated["cron_expression"] == "0 18 * * *"


def test_update_schedule_returns_none_for_missing_id(env):
    assert env.service.update_schedule("does-not-exist", "preset-1", "cron", cron_expression="0 9 * * *") is None


def test_update_schedule_returns_none_for_unknown_new_preset(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")

    assert env.service.update_schedule(created["id"], "does-not-exist", "cron", cron_expression="0 9 * * *") is None


def test_delete_schedule_removes_job_and_status_row(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")
    env.status_repo.set(created["id"], "2026-09-23T00:00:00", "queued")

    assert env.service.delete_schedule(created["id"]) is True
    assert env.service.get_schedule(created["id"]) is None
    assert env.status_repo.get(created["id"]) is None


def test_delete_schedule_returns_false_for_missing_id(env):
    assert env.service.delete_schedule("does-not-exist") is False


def test_pause_and_resume_cron_schedule(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")

    paused = env.service.pause_schedule(created["id"])
    assert paused["paused"] is True

    resumed = env.service.resume_schedule(created["id"])
    assert resumed["paused"] is False


def test_pause_once_schedule_raises_value_error(env):
    run_at = (datetime.now() + timedelta(days=1)).isoformat()
    created = env.service.create_schedule("preset-1", "once", run_at=run_at)

    with pytest.raises(ValueError):
        env.service.pause_schedule(created["id"])


def test_pause_returns_none_for_missing_id(env):
    assert env.service.pause_schedule("does-not-exist") is None


@pytest.mark.asyncio
async def test_run_scheduled_task_enqueues_and_records_status(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")

    await scheduler_module.run_scheduled_task("preset-1", created["id"])

    assert env.queue.calls == [{"goals": ["Do the thing"], "profile": "flash"}]
    status = env.status_repo.get(created["id"])
    assert status["last_status"] == "queued"
    assert status["last_run_at"] is not None


@pytest.mark.asyncio
async def test_run_scheduled_task_handles_deleted_preset(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")
    env.preset_repo.delete("preset-1")

    await scheduler_module.run_scheduled_task("preset-1", created["id"])

    status = env.status_repo.get(created["id"])
    assert status["last_status"] == "error: preset deleted"
    assert env.service.get_schedule(created["id"]) is None
    assert env.queue.calls == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_task_scheduler_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.admin_console.services.task_scheduler_service'`

- [ ] **Step 4: Implement `TaskSchedulerService`**

Create `apps/admin_console/services/task_scheduler_service.py`:

```python
"""Task Scheduler: CRUD over APScheduler jobs that run a Recommended Task
preset once or on a cron schedule.

APScheduler's `SQLAlchemyJobStore` is the system of record for a schedule's
trigger definition, next-run time, and paused state -- this module does not
maintain its own table for any of that. The only custom persistence is
`schedule_status_repository`, which tracks the last run's outcome (a field
APScheduler's job store has no place for).
"""

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


def _build_trigger(
    schedule_type: str, run_at: str | None, cron_expression: str | None
) -> tuple[Any, dict[str, str]]:
    """Validates schedule fields and returns `(trigger, extra_job_kwargs)`.

    Raises `ValueError` on any invalid input -- callers map that to a 422.
    """
    if schedule_type == "once":
        if not run_at:
            raise ValueError("run_at is required for schedule_type 'once'.")
        try:
            run_date = datetime.fromisoformat(run_at)
        except ValueError as exc:
            raise ValueError(f"Invalid run_at datetime: {run_at!r}") from exc
        if run_date <= datetime.now():
            raise ValueError("run_at must be in the future.")
        return DateTrigger(run_date=run_date), {}
    if schedule_type == "cron":
        if not cron_expression:
            raise ValueError("cron_expression is required for schedule_type 'cron'.")
        try:
            trigger = CronTrigger.from_crontab(cron_expression)
        except ValueError as exc:
            raise ValueError(f"Invalid cron expression: {cron_expression!r}") from exc
        return trigger, {"cron_expression": cron_expression}
    raise ValueError(f"Unknown schedule_type: {schedule_type!r}")


class TaskSchedulerService:
    """Wraps an `AsyncIOScheduler` and maps schedule CRUD onto its jobs API."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        # Built lazily in start(), not here: APScheduler binds to the
        # running asyncio event loop at construction time, and this service
        # is instantiated as a module-level singleton at import time --
        # before uvicorn's event loop exists.
        self.scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        if self.scheduler is not None:
            return
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{self.db_path}")}
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None

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
            "run_at": None if is_cron else job.trigger.run_date.isoformat(),
            "cron_expression": job.kwargs.get("cron_expression") if is_cron else None,
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
        trigger, extra_kwargs = _build_trigger(schedule_type, run_at, cron_expression)
        schedule_id = f"sched_{uuid4().hex}"
        job = self.scheduler.add_job(
            run_scheduled_task,
            trigger=trigger,
            args=[preset_id, schedule_id],
            kwargs=extra_kwargs,
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
        trigger, extra_kwargs = _build_trigger(schedule_type, run_at, cron_expression)
        self.scheduler.modify_job(schedule_id, args=[preset_id, schedule_id], kwargs=extra_kwargs)
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_task_scheduler_service.py -v`
Expected: PASS (17 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/admin_console/services/task_scheduler_service.py tests/unit/admin_console/test_task_scheduler_service.py
git commit -m "feat: add TaskSchedulerService backed by APScheduler"
```

---

### Task 4: `schedules` router + `server.py` wiring

**Files:**
- Modify: `apps/admin_console/schemas/task_schema.py`
- Create: `apps/admin_console/routers/schedules.py`
- Modify: `apps/admin_console/server.py`
- Test: `tests/unit/admin_console/test_schedule_endpoints.py`

**Interfaces:**
- Consumes: `TaskSchedulerService` (Task 3) — every method listed in Task 3's "Produces".
- Produces: `ScheduleWrite` Pydantic model; FastAPI router functions `list_schedules()`, `create_schedule(request)`, `update_schedule(schedule_id, request)`, `delete_schedule(schedule_id)`, `pause_schedule(schedule_id)`, `resume_schedule(schedule_id)` under `/api/schedules*`, registered on `app`. Task 5 (the frontend `ScheduleService`) consumes these routes over HTTP.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_schedule_endpoints.py`:

```python
from datetime import datetime, timedelta

from fastapi import HTTPException
import pytest

from apps.admin_console.database.repositories.schedule_status_repository import (
    ScheduleStatusRepository,
)
from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.routers import schedules
from apps.admin_console.schemas.task_schema import ScheduleWrite
from apps.admin_console.services import task_scheduler_service as scheduler_module
from apps.admin_console.services.task_scheduler_service import TaskSchedulerService


def _preset_row(preset_id="preset-1", **overrides):
    row = {
        "id": preset_id,
        "title": "Test Preset",
        "description": "d",
        "goal": "Do the thing",
        "profile": "flash",
        "category": "flash",
        "tag": "Test",
        "apps": [],
        "required_packages": [],
        "match_mode": "any",
        "priority": 60,
        "is_builtin": False,
        "created_at": "2026-09-23T00:00:00+00:00",
        "updated_at": "2026-09-23T00:00:00+00:00",
    }
    row.update(overrides)
    return row


@pytest.fixture
def service(tmp_path, monkeypatch):
    preset_repo = TaskPresetRepository(tmp_path / "presets.db")
    preset_repo.create(_preset_row())
    monkeypatch.setattr(scheduler_module, "task_preset_repository", preset_repo)
    # _serialize_job() reads schedule_status_repository on every list/get/
    # create/update/pause/resume call -- without this, these tests would
    # silently read and write the real project database file.
    status_repo = ScheduleStatusRepository(tmp_path / "status.db")
    monkeypatch.setattr(scheduler_module, "schedule_status_repository", status_repo)

    svc = TaskSchedulerService(db_path=tmp_path / "jobs.db")
    monkeypatch.setattr(scheduler_module, "task_scheduler_service", svc)
    monkeypatch.setattr(schedules, "task_scheduler_service", svc)
    svc.start()
    yield svc
    svc.shutdown()


@pytest.mark.asyncio
async def test_create_schedule_returns_created_row(service):
    request = ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 9 * * *")

    result = await schedules.create_schedule(request)

    assert result["preset_id"] == "preset-1"
    assert result["schedule_type"] == "cron"


@pytest.mark.asyncio
async def test_create_schedule_returns_404_for_unknown_preset(service):
    request = ScheduleWrite(preset_id="does-not-exist", schedule_type="cron", cron_expression="0 9 * * *")

    with pytest.raises(HTTPException) as exc_info:
        await schedules.create_schedule(request)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_create_schedule_returns_422_for_bad_cron(service):
    request = ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="not a cron")

    with pytest.raises(HTTPException) as exc_info:
        await schedules.create_schedule(request)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_list_schedules_returns_created_rows(service):
    await schedules.create_schedule(
        ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 9 * * *")
    )

    result = await schedules.list_schedules()

    assert len(result) == 1


@pytest.mark.asyncio
async def test_update_schedule_returns_404_for_missing_id(service):
    request = ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 18 * * *")

    with pytest.raises(HTTPException) as exc_info:
        await schedules.update_schedule("does-not-exist", request)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_schedule_updates_existing_row(service):
    created = await schedules.create_schedule(
        ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 9 * * *")
    )

    updated = await schedules.update_schedule(
        created["id"],
        ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 18 * * *"),
    )

    assert updated["cron_expression"] == "0 18 * * *"


@pytest.mark.asyncio
async def test_delete_schedule_returns_404_for_missing_id(service):
    with pytest.raises(HTTPException) as exc_info:
        await schedules.delete_schedule("does-not-exist")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_schedule_succeeds_for_existing_row(service):
    created = await schedules.create_schedule(
        ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 9 * * *")
    )

    result = await schedules.delete_schedule(created["id"])

    assert result == {"status": "deleted", "id": created["id"]}


@pytest.mark.asyncio
async def test_pause_and_resume_schedule(service):
    created = await schedules.create_schedule(
        ScheduleWrite(preset_id="preset-1", schedule_type="cron", cron_expression="0 9 * * *")
    )

    paused = await schedules.pause_schedule(created["id"])
    assert paused["paused"] is True

    resumed = await schedules.resume_schedule(created["id"])
    assert resumed["paused"] is False


@pytest.mark.asyncio
async def test_pause_schedule_returns_400_for_once_schedule(service):
    run_at = (datetime.now() + timedelta(days=1)).isoformat()
    created = await schedules.create_schedule(
        ScheduleWrite(preset_id="preset-1", schedule_type="once", run_at=run_at)
    )

    with pytest.raises(HTTPException) as exc_info:
        await schedules.pause_schedule(created["id"])

    assert exc_info.value.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_schedule_endpoints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.admin_console.routers.schedules'` (and `ScheduleWrite` not existing yet in `task_schema`).

- [ ] **Step 3: Add `ScheduleWrite` to `task_schema.py`**

In `apps/admin_console/schemas/task_schema.py`, add this class after `AppUpdate` (the last class in the file):

```python
class ScheduleWrite(BaseModel):
    preset_id: str
    schedule_type: Literal["once", "cron"]
    run_at: str | None = None
    cron_expression: str | None = None
```

- [ ] **Step 4: Create the router**

Create `apps/admin_console/routers/schedules.py`:

```python
"""REST endpoints for Task Scheduler CRUD."""

from fastapi import APIRouter, HTTPException

try:
    from admin_console.schemas.task_schema import ScheduleWrite
    from admin_console.services.task_scheduler_service import task_scheduler_service
except ImportError:
    from apps.admin_console.schemas.task_schema import ScheduleWrite
    from apps.admin_console.services.task_scheduler_service import task_scheduler_service


router = APIRouter(tags=["schedules"])


@router.get("/api/schedules")
async def list_schedules():
    """List all Task Scheduler schedules."""
    return task_scheduler_service.list_schedules()


@router.post("/api/schedules")
async def create_schedule(request: ScheduleWrite):
    """Create a new schedule for an existing task preset."""
    try:
        result = task_scheduler_service.create_schedule(
            request.preset_id,
            request.schedule_type,
            run_at=request.run_at,
            cron_expression=request.cron_expression,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Task preset '{request.preset_id}' not found.")
    return result


@router.put("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, request: ScheduleWrite):
    """Update an existing schedule's preset and/or trigger."""
    try:
        result = task_scheduler_service.update_schedule(
            schedule_id,
            request.preset_id,
            request.schedule_type,
            run_at=request.run_at,
            cron_expression=request.cron_expression,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Schedule '{schedule_id}' or task preset '{request.preset_id}' not found.",
        )
    return result


@router.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    if not task_scheduler_service.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found.")
    return {"status": "deleted", "id": schedule_id}


@router.post("/api/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str):
    """Pause a recurring ('cron') schedule."""
    try:
        result = task_scheduler_service.pause_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found.")
    return result


@router.post("/api/schedules/{schedule_id}/resume")
async def resume_schedule(schedule_id: str):
    """Resume a paused recurring ('cron') schedule."""
    try:
        result = task_scheduler_service.resume_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found.")
    return result
```

- [ ] **Step 5: Wire the router and the scheduler's lifecycle into `server.py`**

In `apps/admin_console/server.py`, apply these four changes:

**5a.** In the `try` import block, add `schedules` to the router import and add the `task_scheduler_service` import:

Find:
```python
    from admin_console.routers import media, replay, sessions, steps, stream, system, tasks
    from admin_console.routers.replay import replay_manager
    from admin_console.services.ipc_service import ipc_service
    from admin_console.services.media_service import media_service
    from admin_console.services.model_service import model_service
    from admin_console.services.task_queue_service import task_queue_service
except ImportError:
    from apps.admin_console.core.security import SameOriginBoundaryMiddleware
    from apps.admin_console.core.state import state
    from apps.admin_console.database.repositories.session_repository import session_repo
    from apps.admin_console.routers import media, replay, sessions, steps, stream, system, tasks
    from apps.admin_console.routers.replay import replay_manager
    from apps.admin_console.services.ipc_service import ipc_service
    from apps.admin_console.services.model_service import model_service
    from apps.admin_console.services.task_queue_service import task_queue_service
```

Replace with:
```python
    from admin_console.routers import media, replay, schedules, sessions, steps, stream, system, tasks
    from admin_console.routers.replay import replay_manager
    from admin_console.services.ipc_service import ipc_service
    from admin_console.services.media_service import media_service
    from admin_console.services.model_service import model_service
    from admin_console.services.task_queue_service import task_queue_service
    from admin_console.services.task_scheduler_service import task_scheduler_service
except ImportError:
    from apps.admin_console.core.security import SameOriginBoundaryMiddleware
    from apps.admin_console.core.state import state
    from apps.admin_console.database.repositories.session_repository import session_repo
    from apps.admin_console.routers import media, replay, schedules, sessions, steps, stream, system, tasks
    from apps.admin_console.routers.replay import replay_manager
    from apps.admin_console.services.ipc_service import ipc_service
    from apps.admin_console.services.model_service import model_service
    from apps.admin_console.services.task_queue_service import task_queue_service
    from apps.admin_console.services.task_scheduler_service import task_scheduler_service
```

**5b.** In `on_startup()`, start the scheduler right after the queue worker:

Find:
```python
    await ipc_service.start_server()
    state.worker_task = asyncio.create_task(task_queue_service.queue_worker())
```

Replace with:
```python
    await ipc_service.start_server()
    state.worker_task = asyncio.create_task(task_queue_service.queue_worker())
    task_scheduler_service.start()
```

**5c.** In `on_shutdown()`, stop the scheduler alongside the IPC server:

Find:
```python
    await ipc_service.stop_server()
    state.ipc_subscribers.clear()
    await asyncio.to_thread(shutdown_awake_service)
```

Replace with:
```python
    await ipc_service.stop_server()
    state.ipc_subscribers.clear()
    task_scheduler_service.shutdown()
    await asyncio.to_thread(shutdown_awake_service)
```

**5d.** Register the router:

Find:
```python
app.include_router(stream.router)
app.include_router(media.router)
app.include_router(sessions.router)
app.include_router(steps.router)
app.include_router(tasks.router)
app.include_router(replay.router)
app.include_router(system.router)
```

Replace with:
```python
app.include_router(stream.router)
app.include_router(media.router)
app.include_router(sessions.router)
app.include_router(steps.router)
app.include_router(tasks.router)
app.include_router(schedules.router)
app.include_router(replay.router)
app.include_router(system.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_schedule_endpoints.py -v`
Expected: PASS (10 tests)

Then confirm `server.py` still imports and behaves correctly after the wiring changes:

Run: `uv run pytest tests/unit/admin_console/test_server_lifecycle.py -v`
Expected: PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add apps/admin_console/schemas/task_schema.py apps/admin_console/routers/schedules.py apps/admin_console/server.py tests/unit/admin_console/test_schedule_endpoints.py
git commit -m "feat: add schedules router and wire TaskSchedulerService into server lifecycle"
```

---

### Task 5: `ScheduleService` (frontend HTTP client)

**Files:**
- Create: `apps/showcase_ui/src/app/core/services/schedule.service.ts`
- Test: `apps/showcase_ui/src/app/core/services/schedule.service.spec.ts`

**Interfaces:**
- Consumes: `/api/schedules*` (Task 4).
- Produces: `Schedule` interface (`id, presetId, presetTitle, scheduleType, runAt, cronExpression, nextRunTime, paused, lastRunAt, lastStatus`), `ScheduleWritePayload` interface (`preset_id, schedule_type, run_at?, cron_expression?`), and `ScheduleService` with `schedules: Signal<Schedule[]>`, `loadSchedules()`, `createSchedule()`, `updateSchedule()`, `deleteSchedule()`, `pauseSchedule()`, `resumeSchedule()`. Tasks 6 and 7 consume this service.

- [ ] **Step 1: Write the failing tests**

Create `apps/showcase_ui/src/app/core/services/schedule.service.spec.ts`:

```typescript
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ScheduleService } from './schedule.service';

describe('ScheduleService', () => {
  let service: ScheduleService;
  let http: HttpTestingController;

  const rawSchedule = (overrides: Record<string, unknown> = {}) => ({
    id: 'sched_1',
    preset_id: 'preset-1',
    preset_title: 'Clear Cache',
    schedule_type: 'cron',
    run_at: null,
    cron_expression: '0 9 * * 1,3,5',
    next_run_time: '2026-09-24T09:00:00',
    paused: false,
    last_run_at: null,
    last_status: null,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ScheduleService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(ScheduleService);
    http = TestBed.inject(HttpTestingController);
    // The constructor eagerly loads the schedule list; drain that request first.
    http.expectOne('/api/schedules').flush([]);
  });

  afterEach(() => http.verify());

  it('maps snake_case API fields to camelCase Schedule fields', () => {
    service.loadSchedules().subscribe();
    const req = http.expectOne('/api/schedules');
    req.flush([rawSchedule()]);

    const loaded = service.schedules();
    expect(loaded.length).toBe(1);
    expect(loaded[0].presetId).toBe('preset-1');
    expect(loaded[0].cronExpression).toBe('0 9 * * 1,3,5');
  });

  it('creates a schedule then refreshes the list', () => {
    service.createSchedule({
      preset_id: 'preset-1',
      schedule_type: 'cron',
      cron_expression: '0 9 * * 1,3,5'
    }).subscribe();

    const createReq = http.expectOne('/api/schedules');
    expect(createReq.request.method).toBe('POST');
    createReq.flush(rawSchedule());

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule()]);

    expect(service.schedules().length).toBe(1);
  });

  it('updates a schedule by id then refreshes the list', () => {
    service.updateSchedule('sched_1', {
      preset_id: 'preset-1',
      schedule_type: 'cron',
      cron_expression: '0 18 * * *'
    }).subscribe();

    const updateReq = http.expectOne('/api/schedules/sched_1');
    expect(updateReq.request.method).toBe('PUT');
    updateReq.flush(rawSchedule({ cron_expression: '0 18 * * *' }));

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule({ cron_expression: '0 18 * * *' })]);

    expect(service.schedules()[0].cronExpression).toBe('0 18 * * *');
  });

  it('deletes a schedule by id then refreshes the list', () => {
    service.deleteSchedule('sched_1').subscribe();

    const deleteReq = http.expectOne('/api/schedules/sched_1');
    expect(deleteReq.request.method).toBe('DELETE');
    deleteReq.flush({ status: 'deleted', id: 'sched_1' });

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([]);

    expect(service.schedules()).toEqual([]);
  });

  it('pauses a schedule then refreshes the list', () => {
    service.pauseSchedule('sched_1').subscribe();

    const pauseReq = http.expectOne('/api/schedules/sched_1/pause');
    expect(pauseReq.request.method).toBe('POST');
    pauseReq.flush(rawSchedule({ paused: true }));

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule({ paused: true })]);

    expect(service.schedules()[0].paused).toBe(true);
  });

  it('resumes a schedule then refreshes the list', () => {
    service.resumeSchedule('sched_1').subscribe();

    const resumeReq = http.expectOne('/api/schedules/sched_1/resume');
    expect(resumeReq.request.method).toBe('POST');
    resumeReq.flush(rawSchedule({ paused: false }));

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule({ paused: false })]);

    expect(service.schedules()[0].paused).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

If `ng test` can run in your environment: `cd apps/showcase_ui && npx ng test --watch=false --include='**/schedule.service.spec.ts'`, expect FAIL (module doesn't exist yet).
If `ng test` cannot launch a browser in your sandbox: skip to Step 3 and rely on `ng build` plus a manual trace, exactly as noted in the plan header.

- [ ] **Step 3: Implement `ScheduleService`**

Create `apps/showcase_ui/src/app/core/services/schedule.service.ts`:

```typescript
import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, tap } from 'rxjs';

export interface ScheduleWritePayload {
  preset_id: string;
  schedule_type: 'once' | 'cron';
  run_at?: string | null;
  cron_expression?: string | null;
}

export interface Schedule {
  id: string;
  presetId: string;
  presetTitle: string;
  scheduleType: 'once' | 'cron';
  runAt: string | null;
  cronExpression: string | null;
  nextRunTime: string | null;
  paused: boolean;
  lastRunAt: string | null;
  lastStatus: string | null;
}

interface RawSchedule {
  id: string;
  preset_id: string;
  preset_title: string;
  schedule_type: 'once' | 'cron';
  run_at: string | null;
  cron_expression: string | null;
  next_run_time: string | null;
  paused: boolean;
  last_run_at: string | null;
  last_status: string | null;
}

function mapSchedule(raw: RawSchedule): Schedule {
  return {
    id: raw.id,
    presetId: raw.preset_id,
    presetTitle: raw.preset_title,
    scheduleType: raw.schedule_type,
    runAt: raw.run_at,
    cronExpression: raw.cron_expression,
    nextRunTime: raw.next_run_time,
    paused: raw.paused,
    lastRunAt: raw.last_run_at,
    lastStatus: raw.last_status
  };
}

@Injectable({
  providedIn: 'root'
})
export class ScheduleService {
  private http = inject(HttpClient);

  public schedules = signal<Schedule[]>([]);

  constructor() {
    this.loadSchedules().subscribe();
  }

  /**
   * Fetches all schedules from the backend and replaces `schedules`.
   * Called on service init and after every mutation.
   */
  public loadSchedules(): Observable<RawSchedule[]> {
    return this.http.get<RawSchedule[]>('/api/schedules').pipe(
      tap({
        next: (response) => this.schedules.set(response.map(mapSchedule)),
        error: (err) => console.error('Failed to load schedules:', err)
      })
    );
  }

  public createSchedule(payload: ScheduleWritePayload): Observable<Schedule> {
    return this.http.post<RawSchedule>('/api/schedules', payload).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }

  public updateSchedule(id: string, payload: ScheduleWritePayload): Observable<Schedule> {
    return this.http.put<RawSchedule>(`/api/schedules/${encodeURIComponent(id)}`, payload).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }

  public deleteSchedule(id: string): Observable<{ status: string; id: string }> {
    return this.http.delete<{ status: string; id: string }>(`/api/schedules/${encodeURIComponent(id)}`).pipe(
      tap(() => this.loadSchedules().subscribe())
    );
  }

  public pauseSchedule(id: string): Observable<Schedule> {
    return this.http.post<RawSchedule>(`/api/schedules/${encodeURIComponent(id)}/pause`, {}).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }

  public resumeSchedule(id: string): Observable<Schedule> {
    return this.http.post<RawSchedule>(`/api/schedules/${encodeURIComponent(id)}/resume`, {}).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }
}
```

Remember to add the Apache 2.0 license header block at the top of this file (see Global Constraints).

- [ ] **Step 4: Run the tests to verify they pass**

If `ng test` works: `cd apps/showcase_ui && npx ng test --watch=false --include='**/schedule.service.spec.ts'`, expect PASS (6 tests).
If not: `cd apps/showcase_ui && npx ng build`. Expect a clean build (this is a new, self-contained file with no other consumers yet). Then manually trace each of the 6 spec assertions against `schedule.service.ts` and confirm each would pass. Write that trace into your report.

- [ ] **Step 5: Commit**

```bash
git add apps/showcase_ui/src/app/core/services/schedule.service.ts apps/showcase_ui/src/app/core/services/schedule.service.spec.ts
git commit -m "feat: add ScheduleService for Task Scheduler API access"
```

---

### Task 6: `ScheduleFormComponent` (create/edit modal)

**Files:**
- Create: `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.ts`
- Create: `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.html`
- Create: `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.scss`
- Test: `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.spec.ts`

**Interfaces:**
- Consumes: `TaskRecommendationService.allTasks: Signal<SmartSuggestion[]>` (existing, each item has `id`/`title`) for the preset dropdown; `Schedule`, `ScheduleWritePayload` (Task 5).
- Produces: `ScheduleFormComponent` with `@Input() editingSchedule: Schedule | null`, `@Input() errorText: string | null`, `@Output() save: EventEmitter<ScheduleWritePayload>`, `@Output() cancel: EventEmitter<void>`. Task 7 consumes this as `<app-schedule-form>`.

- [ ] **Step 1: Write the failing tests**

Create `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.spec.ts`:

```typescript
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Schedule } from '../../core/services/schedule.service';
import { ScheduleFormComponent } from './schedule-form.component';

describe('ScheduleFormComponent', () => {
  let fixture: ComponentFixture<ScheduleFormComponent>;
  let component: ScheduleFormComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ScheduleFormComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(ScheduleFormComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    // TaskRecommendationService (injected for the preset dropdown) eagerly loads its catalog.
    http.expectOne('/api/tasks/catalog').flush({
      tasks: [
        {
          id: 'preset-1',
          title: 'Clear Cache',
          description: 'd',
          goal: 'g',
          profile: 'flash',
          category: 'flash',
          tag: 'Test',
          apps: [],
          required_packages: [],
          match_mode: 'any',
          priority: 60,
          is_builtin: false
        }
      ]
    });
  });

  afterEach(() => http.verify());

  it('defaults to the first preset and cron type in create mode', () => {
    component.ngOnChanges({} as never);

    expect(component.presetId()).toBe('preset-1');
    expect(component.scheduleType()).toBe('cron');
    expect(component.isValid).toBeFalse();
  });

  it('pre-fills fields when editing an existing schedule', () => {
    const schedule: Schedule = {
      id: 'sched_1',
      presetId: 'preset-1',
      presetTitle: 'Clear Cache',
      scheduleType: 'once',
      runAt: '2026-09-25T09:00',
      cronExpression: null,
      nextRunTime: '2026-09-25T09:00:00',
      paused: false,
      lastRunAt: null,
      lastStatus: null
    };
    component.editingSchedule = schedule;

    component.ngOnChanges({ editingSchedule: {} as never });

    expect(component.presetId()).toBe('preset-1');
    expect(component.scheduleType()).toBe('once');
    expect(component.runAt()).toBe('2026-09-25T09:00');
  });

  it('requires a cron expression when schedule type is cron', () => {
    component.ngOnChanges({} as never);

    expect(component.isValid).toBeFalse();

    component.cronExpression.set('0 9 * * *');

    expect(component.isValid).toBeTrue();
  });

  it('requires a run-at datetime when schedule type is once', () => {
    component.ngOnChanges({} as never);
    component.scheduleType.set('once');

    expect(component.isValid).toBeFalse();

    component.runAt.set('2026-09-25T09:00');

    expect(component.isValid).toBeTrue();
  });

  it('emits save with a cron payload', () => {
    component.ngOnChanges({} as never);
    component.cronExpression.set('0 9 * * 1,3,5');

    let emitted: unknown = null;
    component.save.subscribe(v => (emitted = v));
    component.onSave();

    expect(emitted).toEqual({
      preset_id: 'preset-1',
      schedule_type: 'cron',
      run_at: null,
      cron_expression: '0 9 * * 1,3,5'
    });
  });

  it('emits save with a once payload', () => {
    component.ngOnChanges({} as never);
    component.scheduleType.set('once');
    component.runAt.set('2026-09-25T09:00');

    let emitted: unknown = null;
    component.save.subscribe(v => (emitted = v));
    component.onSave();

    expect(emitted).toEqual({
      preset_id: 'preset-1',
      schedule_type: 'once',
      run_at: '2026-09-25T09:00',
      cron_expression: null
    });
  });

  it('emits cancel', () => {
    let called = false;
    component.cancel.subscribe(() => (called = true));
    component.onCancel();
    expect(called).toBeTrue();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

If `ng test` can run in your environment: `cd apps/showcase_ui && npx ng test --watch=false --include='**/schedule-form.component.spec.ts'`, expect FAIL (module doesn't exist yet).
If not: skip to Step 3 and rely on `ng build` plus a manual trace.

- [ ] **Step 3: Implement `ScheduleFormComponent`**

Create `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.ts`:

```typescript
import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TaskRecommendationService } from '../../core/services/task-recommendation.service';
import { Schedule, ScheduleWritePayload } from '../../core/services/schedule.service';

@Component({
  selector: 'app-schedule-form',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './schedule-form.component.html',
  styleUrl: './schedule-form.component.scss'
})
export class ScheduleFormComponent implements OnChanges {
  @Input() editingSchedule: Schedule | null = null;
  @Input() errorText: string | null = null;
  @Output() save = new EventEmitter<ScheduleWritePayload>();
  @Output() cancel = new EventEmitter<void>();

  public taskRecService = inject(TaskRecommendationService);

  public presetId = signal<string>('');
  public scheduleType = signal<'once' | 'cron'>('cron');
  public runAt = signal<string>('');
  public cronExpression = signal<string>('');

  ngOnChanges(_changes: SimpleChanges): void {
    const schedule = this.editingSchedule;
    const tasks = this.taskRecService.allTasks();
    this.presetId.set(schedule?.presetId ?? tasks[0]?.id ?? '');
    this.scheduleType.set(schedule?.scheduleType ?? 'cron');
    this.runAt.set(schedule?.runAt ?? '');
    this.cronExpression.set(schedule?.cronExpression ?? '');
  }

  public get isValid(): boolean {
    if (!this.presetId()) {
      return false;
    }
    return this.scheduleType() === 'once'
      ? this.runAt().trim().length > 0
      : this.cronExpression().trim().length > 0;
  }

  public onSave(): void {
    if (!this.isValid) {
      return;
    }
    this.save.emit({
      preset_id: this.presetId(),
      schedule_type: this.scheduleType(),
      run_at: this.scheduleType() === 'once' ? this.runAt() : null,
      cron_expression: this.scheduleType() === 'cron' ? this.cronExpression().trim() : null
    });
  }

  public onCancel(): void {
    this.cancel.emit();
  }
}
```

Remember the license header at the top.

Create `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.html`:

```html
<div class="sf-overlay" (click)="onCancel()">
  <div class="sf-modal" (click)="$event.stopPropagation()">
    <div class="sf-header">
      <h3>{{ editingSchedule ? 'Edit Schedule' : 'New Schedule' }}</h3>
      <button type="button" class="sf-close-btn" (click)="onCancel()">
        <span class="material-symbols-outlined">close</span>
      </button>
    </div>

    <div class="sf-body">
      <label class="sf-field">
        <span class="sf-label">Task Preset</span>
        <select [ngModel]="presetId()" (ngModelChange)="presetId.set($event)">
          @for (task of taskRecService.allTasks(); track task.id) {
            <option [value]="task.id">{{ task.title }}</option>
          }
        </select>
      </label>

      <div class="sf-field">
        <span class="sf-label">Schedule Type</span>
        <div class="sf-type-toggle">
          <button type="button" [class.active]="scheduleType() === 'once'" (click)="scheduleType.set('once')">Once</button>
          <button type="button" [class.active]="scheduleType() === 'cron'" (click)="scheduleType.set('cron')">Cron</button>
        </div>
      </div>

      @if (scheduleType() === 'once') {
        <label class="sf-field">
          <span class="sf-label">Run At</span>
          <input type="datetime-local" [ngModel]="runAt()" (ngModelChange)="runAt.set($event)" />
        </label>
      } @else {
        <label class="sf-field">
          <span class="sf-label">Cron Expression</span>
          <input type="text" [ngModel]="cronExpression()" (ngModelChange)="cronExpression.set($event)" placeholder="e.g. 0 9 * * 1,3,5" />
        </label>
      }
    </div>

    <div class="sf-footer">
      @if (errorText) {
        <span class="sf-error">{{ errorText }}</span>
      }
      <div class="sf-footer-actions">
        <button type="button" class="sf-btn-secondary" (click)="onCancel()">Cancel</button>
        <button type="button" class="sf-btn-primary" [disabled]="!isValid" (click)="onSave()">Save</button>
      </div>
    </div>
  </div>
</div>
```

Create `apps/showcase_ui/src/app/components/schedule-form/schedule-form.component.scss`:

```scss
.sf-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 16px;
}

.sf-modal {
  width: 100%;
  max-width: 420px;
  max-height: 88vh;
  overflow-y: auto;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 20px 48px -12px rgba(15, 23, 42, 0.35);
  display: flex;
  flex-direction: column;
}

.sf-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.85);

  h3 {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    color: #0f172a;
  }

  .sf-close-btn {
    border: none;
    background: transparent;
    color: #64748b;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 8px;

    &:hover {
      background: #f1f5f9;
      color: #0f172a;
    }
  }
}

.sf-body {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sf-field {
  display: flex;
  flex-direction: column;
  gap: 6px;

  .sf-label {
    font-size: 12px;
    font-weight: 600;
    color: #475569;
  }

  input,
  select {
    border: 1px solid rgba(203, 213, 225, 0.9);
    border-radius: 10px;
    padding: 8px 10px;
    font-size: 13px;
    font-family: inherit;
    color: #0f172a;
    background: #ffffff;

    &:focus {
      outline: none;
      border-color: #1a73e8;
      box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }
  }
}

.sf-type-toggle {
  display: flex;
  gap: 6px;

  button {
    flex: 1;
    padding: 7px 0;
    border-radius: 9px;
    border: 1px solid rgba(203, 213, 225, 0.9);
    background: #ffffff;
    color: #475569;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;

    &.active {
      background: rgba(26, 115, 232, 0.1);
      border-color: rgba(26, 115, 232, 0.4);
      color: #1a73e8;
    }
  }
}

.sf-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  padding: 14px 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.85);

  .sf-error {
    flex: 1 1 auto;
    color: #dc2626;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
    margin-right: auto;
  }

  .sf-footer-actions {
    display: flex;
    gap: 8px;
    margin-left: auto;
  }
}

.sf-btn-secondary,
.sf-btn-primary {
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
}

.sf-btn-secondary {
  background: #ffffff;
  border-color: rgba(203, 213, 225, 0.9);
  color: #475569;

  &:hover {
    background: #f8fafc;
  }
}

.sf-btn-primary {
  background: #1a73e8;
  color: #ffffff;

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &:hover:not(:disabled) {
    background: #1558b8;
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

If `ng test` works: `cd apps/showcase_ui && npx ng test --watch=false --include='**/schedule-form.component.spec.ts'`, expect PASS (7 tests).
If not: `cd apps/showcase_ui && npx ng build`. Expect a clean build. Then manually trace each of the 7 spec assertions against `schedule-form.component.ts` and confirm each would pass. Write that trace into your report.

- [ ] **Step 5: Commit**

```bash
git add apps/showcase_ui/src/app/components/schedule-form/
git commit -m "feat: add ScheduleFormComponent for schedule create/edit"
```

---

### Task 7: `SchedulesComponent` page, routing, and nav tab

**Files:**
- Create: `apps/showcase_ui/src/app/pages/schedules/schedules.component.ts`
- Create: `apps/showcase_ui/src/app/pages/schedules/schedules.component.html`
- Create: `apps/showcase_ui/src/app/pages/schedules/schedules.component.scss`
- Modify: `apps/showcase_ui/src/app/app.routes.ts`
- Modify: `apps/showcase_ui/src/app/components/nav-switcher/nav-switcher.component.ts`

**Interfaces:**
- Consumes: `ScheduleService` (Task 5), `ScheduleFormComponent` (Task 6).
- Produces: a reachable `/schedules` page. Nothing downstream consumes this component (it is the final task).

No page-level component in this codebase (`home`, `workspace`, `legacy-workspace`) has a `.spec.ts` file — only reusable form components and services do. This task follows that convention: verify via `ng build` (or a real page load if you can run the dev server) plus a manual trace, not a spec file.

- [ ] **Step 1: Implement `SchedulesComponent`**

Create `apps/showcase_ui/src/app/pages/schedules/schedules.component.ts`:

```typescript
import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { Schedule, ScheduleService, ScheduleWritePayload } from '../../core/services/schedule.service';
import { ScheduleFormComponent } from '../../components/schedule-form/schedule-form.component';

@Component({
  selector: 'app-schedules',
  standalone: true,
  imports: [ScheduleFormComponent],
  templateUrl: './schedules.component.html',
  styleUrl: './schedules.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SchedulesComponent {
  public scheduleService = inject(ScheduleService);

  public showModal = signal<boolean>(false);
  public editingSchedule = signal<Schedule | null>(null);
  public modalError = signal<string | null>(null);
  public errorMessage = signal<string | null>(null);

  public openAddModal(): void {
    this.editingSchedule.set(null);
    this.modalError.set(null);
    this.showModal.set(true);
  }

  public openEditModal(schedule: Schedule): void {
    this.editingSchedule.set(schedule);
    this.modalError.set(null);
    this.showModal.set(true);
  }

  public closeModal(): void {
    this.showModal.set(false);
    this.editingSchedule.set(null);
    this.modalError.set(null);
  }

  public saveSchedule(payload: ScheduleWritePayload): void {
    const editing = this.editingSchedule();
    const request$ = editing
      ? this.scheduleService.updateSchedule(editing.id, payload)
      : this.scheduleService.createSchedule(payload);
    request$.subscribe({
      next: () => this.closeModal(),
      error: (err) => {
        const message = err?.error?.detail || 'Failed to save schedule.';
        this.errorMessage.set(message);
        this.modalError.set(message);
        this.scheduleService.loadSchedules().subscribe();
      }
    });
  }

  public deleteSchedule(schedule: Schedule): void {
    if (!confirm(`Delete the schedule for "${schedule.presetTitle}"?`)) {
      return;
    }
    this.scheduleService.deleteSchedule(schedule.id).subscribe({
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to delete schedule.');
        this.scheduleService.loadSchedules().subscribe();
      }
    });
  }

  public togglePause(schedule: Schedule): void {
    const request$ = schedule.paused
      ? this.scheduleService.resumeSchedule(schedule.id)
      : this.scheduleService.pauseSchedule(schedule.id);
    request$.subscribe({
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to update schedule.');
        this.scheduleService.loadSchedules().subscribe();
      }
    });
  }
}
```

Remember the license header at the top.

Create `apps/showcase_ui/src/app/pages/schedules/schedules.component.html`:

```html
<div class="sp-page">
  <div class="sp-header">
    <h2>Task Scheduler</h2>
    <button type="button" class="sp-btn-primary" (click)="openAddModal()">
      <span class="material-symbols-outlined">add</span>
      <span>New Schedule</span>
    </button>
  </div>

  @if (errorMessage()) {
    <div class="sp-error-banner">{{ errorMessage() }}</div>
  }

  <div class="sp-cards-grid">
    @for (schedule of scheduleService.schedules(); track schedule.id) {
      <div class="sp-card">
        <div class="sp-card-header">
          <span class="sp-card-title">{{ schedule.presetTitle }}</span>
          <span class="sp-card-type" [class.sp-type-once]="schedule.scheduleType === 'once'">
            {{ schedule.scheduleType === 'once' ? 'Once' : 'Cron' }}
          </span>
        </div>
        <div class="sp-card-detail">
          {{ schedule.scheduleType === 'once' ? schedule.runAt : schedule.cronExpression }}
        </div>
        <div class="sp-card-meta">
          <span>Next run: {{ schedule.nextRunTime || (schedule.paused ? 'Paused' : '—') }}</span>
          @if (schedule.lastRunAt) {
            <span>Last run: {{ schedule.lastRunAt }} ({{ schedule.lastStatus }})</span>
          }
        </div>
        <div class="sp-card-actions">
          @if (schedule.scheduleType === 'cron') {
            <button type="button" class="sp-btn-secondary" (click)="togglePause(schedule)">
              {{ schedule.paused ? 'Resume' : 'Pause' }}
            </button>
          }
          <button type="button" class="sp-btn-secondary" (click)="openEditModal(schedule)">Edit</button>
          <button type="button" class="sp-btn-danger" (click)="deleteSchedule(schedule)">Delete</button>
        </div>
      </div>
    }
  </div>

  @if (showModal()) {
    <app-schedule-form
      [editingSchedule]="editingSchedule()"
      [errorText]="modalError()"
      (save)="saveSchedule($event)"
      (cancel)="closeModal()"
    />
  }
</div>
```

Create `apps/showcase_ui/src/app/pages/schedules/schedules.component.scss`:

```scss
.sp-page {
  padding: 32px 40px 80px;
  max-width: 1080px;
  margin: 0 auto;
}

.sp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
  }
}

.sp-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border-radius: 10px;
  border: none;
  background: #1a73e8;
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;

  &:hover {
    background: #1558b8;
  }
}

.sp-error-banner {
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 16px;
}

.sp-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.sp-card {
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 14px;
  padding: 16px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sp-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sp-card-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.sp-card-type {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(26, 115, 232, 0.1);
  color: #1a73e8;

  &.sp-type-once {
    background: rgba(100, 116, 139, 0.12);
    color: #475569;
  }
}

.sp-card-detail {
  font-size: 12.5px;
  color: #475569;
  font-family: monospace;
}

.sp-card-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11.5px;
  color: #64748b;
}

.sp-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.sp-btn-secondary,
.sp-btn-danger {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid rgba(203, 213, 225, 0.9);
  background: #ffffff;
  color: #475569;

  &:hover {
    background: #f8fafc;
  }
}

.sp-btn-danger:hover {
  border-color: rgba(220, 38, 38, 0.4);
  color: #dc2626;
}
```

- [ ] **Step 2: Wire the route**

In `apps/showcase_ui/src/app/app.routes.ts`, find:

```typescript
import { Routes } from '@angular/router';
import { HomeComponent } from './pages/home/home.component';
import { WorkspaceComponent } from './pages/workspace/workspace.component';
import { LegacyWorkspaceComponent } from './pages/legacy-workspace/legacy-workspace.component';

export const routes: Routes = [
  { path: '', component: HomeComponent },
  { path: 'workspace', component: WorkspaceComponent },
  { path: 'check', component: LegacyWorkspaceComponent },
  { path: '**', redirectTo: '' }
];
```

Replace with:

```typescript
import { Routes } from '@angular/router';
import { HomeComponent } from './pages/home/home.component';
import { WorkspaceComponent } from './pages/workspace/workspace.component';
import { LegacyWorkspaceComponent } from './pages/legacy-workspace/legacy-workspace.component';
import { SchedulesComponent } from './pages/schedules/schedules.component';

export const routes: Routes = [
  { path: '', component: HomeComponent },
  { path: 'workspace', component: WorkspaceComponent },
  { path: 'schedules', component: SchedulesComponent },
  { path: 'check', component: LegacyWorkspaceComponent },
  { path: '**', redirectTo: '' }
];
```

- [ ] **Step 3: Add the nav tab**

In `apps/showcase_ui/src/app/components/nav-switcher/nav-switcher.component.ts`, find:

```typescript
      <a 
        routerLink="/workspace" 
        routerLinkActive="active" 
        class="nav-tab-btn"
        title="Open Workspace"
      >
        <span class="material-symbols-outlined tab-icon">space_dashboard</span>
        <span class="tab-label">Workspace</span>
      </a>
    </nav>
  `,
```

Replace with:

```typescript
      <a 
        routerLink="/workspace" 
        routerLinkActive="active" 
        class="nav-tab-btn"
        title="Open Workspace"
      >
        <span class="material-symbols-outlined tab-icon">space_dashboard</span>
        <span class="tab-label">Workspace</span>
      </a>
      <a 
        routerLink="/schedules" 
        routerLinkActive="active" 
        class="nav-tab-btn"
        title="Task Scheduler"
      >
        <span class="material-symbols-outlined tab-icon">schedule</span>
        <span class="tab-label">Scheduler</span>
      </a>
    </nav>
  `,
```

- [ ] **Step 4: Verify**

If you can run the dev server in your environment: start it, navigate to `/schedules`, confirm the page loads, create a cron schedule against a real (or seeded) task preset, confirm it appears with a next-run time, pause/resume it, edit it, delete it. Also click the new "Scheduler" nav tab from `/` and confirm it navigates correctly.

If not: `cd apps/showcase_ui && npx ng build`. Expect a fully clean build (this is the last file in the feature, so nothing should be left broken). Then manually trace: read `schedules.component.html` against `schedules.component.ts` and confirm every binding (`scheduleService.schedules()`, `openAddModal`, `openEditModal`, `deleteSchedule`, `togglePause`, `saveSchedule`, `closeModal`) resolves to a real method/property with matching types, and that `app.routes.ts` / `nav-switcher.component.ts` reference `SchedulesComponent` correctly. Write that trace into your report.

- [ ] **Step 5: Commit**

```bash
git add apps/showcase_ui/src/app/pages/schedules/ apps/showcase_ui/src/app/app.routes.ts apps/showcase_ui/src/app/components/nav-switcher/nav-switcher.component.ts
git commit -m "feat: add Task Scheduler page, route, and nav tab"
```
