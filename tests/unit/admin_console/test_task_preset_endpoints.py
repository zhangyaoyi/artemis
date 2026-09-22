from fastapi import HTTPException
import pytest

from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.routers import tasks
from apps.admin_console.schemas.task_schema import TaskPresetWrite
from apps.admin_console.services.task_preset_catalog import TaskRecommendationEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    test_engine = TaskRecommendationEngine(repository=repo)
    monkeypatch.setattr(tasks, "task_recommendation_engine", test_engine)
    return test_engine


@pytest.mark.asyncio
async def test_create_task_preset_returns_created_row(engine):
    request = TaskPresetWrite(
        title="My Task",
        description="desc",
        goal="goal",
        profile="flash",
        app_pkgs=["com.android.chrome"],
    )

    result = await tasks.create_task_preset(request)

    assert result["title"] == "My Task"
    assert result["is_builtin"] is False


@pytest.mark.asyncio
async def test_create_task_preset_rejects_unknown_package(engine):
    request = TaskPresetWrite(
        title="Bad",
        description="desc",
        goal="goal",
        profile="flash",
        app_pkgs=["com.unknown.app"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await tasks.create_task_preset(request)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_task_preset_returns_404_for_missing_id(engine):
    request = TaskPresetWrite(
        title="X", description="d", goal="g", profile="flash", app_pkgs=["com.android.chrome"]
    )

    with pytest.raises(HTTPException) as exc_info:
        await tasks.update_task_preset("does-not-exist", request)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_task_preset_updates_existing_row(engine):
    created = await tasks.create_task_preset(
        TaskPresetWrite(
            title="Orig", description="d", goal="g", profile="flash", app_pkgs=["com.android.chrome"]
        )
    )

    updated = await tasks.update_task_preset(
        created["id"],
        TaskPresetWrite(
            title="Renamed", description="d", goal="g", profile="flash", app_pkgs=["com.android.chrome"]
        ),
    )

    assert updated["title"] == "Renamed"
    assert updated["id"] == created["id"]


@pytest.mark.asyncio
async def test_delete_task_preset_returns_404_for_missing_id(engine):
    with pytest.raises(HTTPException) as exc_info:
        await tasks.delete_task_preset("does-not-exist")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_preset_succeeds_for_existing_row(engine):
    created = await tasks.create_task_preset(
        TaskPresetWrite(
            title="X", description="d", goal="g", profile="flash", app_pkgs=["com.android.chrome"]
        )
    )

    result = await tasks.delete_task_preset(created["id"])

    assert result == {"status": "deleted", "id": created["id"]}
