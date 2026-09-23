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
