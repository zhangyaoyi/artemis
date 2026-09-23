import asyncio
from datetime import datetime, timedelta, timezone
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
    yield SimpleNamespace(
        service=svc, preset_repo=preset_repo, status_repo=status_repo, queue=fake_queue
    )
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


def test_once_schedule_run_at_round_trips_through_update(env):
    """The `run_at` a create returns must be accepted verbatim by update().

    Regression: `DateTrigger` localizes a naive run_date, so serializing it
    with `.isoformat()` produced an offset-bearing string that (a) renders
    blank in `<input type="datetime-local">` and (b) blew up in
    `_build_trigger` with an uncaught `TypeError` (aware vs. naive compare)
    when the UI saved it straight back -- surfacing as a 500 on edit.
    """
    run_at = (datetime.now() + timedelta(days=1)).isoformat()
    created = env.service.create_schedule("preset-1", "once", run_at=run_at)

    # Exactly what the UI puts in the datetime-local input and sends back.
    assert "+" not in created["run_at"]
    assert created["run_at"] == datetime.strptime(created["run_at"], "%Y-%m-%dT%H:%M").strftime(
        "%Y-%m-%dT%H:%M"
    )

    updated = env.service.update_schedule(
        created["id"], "preset-1", "once", run_at=created["run_at"]
    )

    assert updated is not None
    assert updated["schedule_type"] == "once"
    assert updated["run_at"] == created["run_at"]


@pytest.mark.parametrize("offset_hours", [0, 8, -5])
def test_build_trigger_accepts_timezone_aware_run_at(offset_hours):
    """An offset-bearing `run_at` must not blow up the past-datetime check.

    Regression: `run_date <= datetime.now()` compared an aware datetime to a
    naive one, raising `TypeError` -- which the router's `except ValueError`
    does not catch, so it surfaced as a 500 instead of a 422.
    """
    tz = timezone(timedelta(hours=offset_hours))
    future = (datetime.now(tz) + timedelta(days=1)).isoformat()
    past = (datetime.now(tz) - timedelta(days=1)).isoformat()

    assert scheduler_module._build_trigger("once", future, None) is not None
    with pytest.raises(ValueError):
        scheduler_module._build_trigger("once", past, None)


def test_create_schedule_returns_none_for_unknown_preset(env):
    assert (
        env.service.create_schedule("does-not-exist", "cron", cron_expression="0 9 * * *") is None
    )


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

    updated = env.service.update_schedule(
        created["id"], "preset-2", "cron", cron_expression="0 18 * * *"
    )

    assert updated["preset_id"] == "preset-2"
    assert updated["preset_title"] == "Other Preset"
    assert updated["cron_expression"] == "0 18 * * *"


def test_update_schedule_returns_none_for_missing_id(env):
    assert (
        env.service.update_schedule(
            "does-not-exist", "preset-1", "cron", cron_expression="0 9 * * *"
        )
        is None
    )


def test_update_schedule_returns_none_for_unknown_new_preset(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")

    assert (
        env.service.update_schedule(
            created["id"], "does-not-exist", "cron", cron_expression="0 9 * * *"
        )
        is None
    )


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
async def test_job_fires_via_real_scheduler_loop(tmp_path, monkeypatch):
    """A `once` schedule actually fires through APScheduler's own timer.

    Deliberately self-contained (no `env` fixture): `start()` must be called
    from *inside* a running event loop so `asyncio.get_running_loop()`
    succeeds and the scheduler binds to the real loop -- the production path
    taken by `on_startup()`. Every other test here starts the service
    synchronously, which takes the unbound-loop fallback branch where
    triggers never fire, and invokes `run_scheduled_task` as a plain call.
    """
    preset_repo = TaskPresetRepository(tmp_path / "presets.db")
    preset_repo.create(_preset_row("preset-1", title="Test Preset"))
    status_repo = ScheduleStatusRepository(tmp_path / "status.db")
    fake_queue = _FakeTaskQueueService()

    monkeypatch.setattr(scheduler_module, "task_preset_repository", preset_repo)
    monkeypatch.setattr(scheduler_module, "schedule_status_repository", status_repo)
    monkeypatch.setattr(scheduler_module, "task_queue_service", fake_queue)

    svc = TaskSchedulerService(db_path=tmp_path / "jobs.db")
    monkeypatch.setattr(scheduler_module, "task_scheduler_service", svc)
    svc.start()
    assert svc._owned_event_loop is None, "start() should have bound to the running loop"

    try:
        run_at = (datetime.now() + timedelta(seconds=1)).isoformat()
        created = svc.create_schedule("preset-1", "once", run_at=run_at)

        # Generous margin: this assertion is about *whether* the scheduler
        # fires the job at all, not about its timing precision.
        for _ in range(40):
            await asyncio.sleep(0.1)
            if status_repo.get(created["id"]) is not None:
                break

        status = status_repo.get(created["id"])
        assert status is not None, "scheduler never fired the job"
        assert status["last_status"] == "queued"
        assert fake_queue.calls == [{"goals": ["Do the thing"], "profile": "flash"}]
    finally:
        svc.shutdown()


@pytest.mark.asyncio
async def test_run_scheduled_task_handles_deleted_preset(env):
    created = env.service.create_schedule("preset-1", "cron", cron_expression="0 9 * * *")
    env.preset_repo.delete("preset-1")

    await scheduler_module.run_scheduled_task("preset-1", created["id"])

    status = env.status_repo.get(created["id"])
    assert status["last_status"] == "error: preset deleted"
    assert env.service.get_schedule(created["id"]) is None
    assert env.queue.calls == []
