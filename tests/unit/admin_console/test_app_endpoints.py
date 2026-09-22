from fastapi import HTTPException
import pytest

from apps.admin_console.database.repositories.app_repository import AppRepository
from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.routers import tasks
from apps.admin_console.schemas.task_schema import AppCreate, AppUpdate, TaskPresetWrite
from apps.admin_console.services.task_preset_catalog import TaskRecommendationEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    apps_repo = AppRepository(tmp_path / "apps.db")
    test_engine = TaskRecommendationEngine(repository=repo, app_repository=apps_repo)
    monkeypatch.setattr(tasks, "task_recommendation_engine", test_engine)
    return test_engine


@pytest.mark.asyncio
async def test_get_apps_returns_seeded_registry(engine):
    apps = await tasks.get_apps()

    assert len(apps) > 0
    assert any(a["pkg"] == "com.android.chrome" for a in apps)


@pytest.mark.asyncio
async def test_create_app_returns_created_row(engine):
    request = AppCreate(pkg="com.example.newapp", name="New App", icon="star", category="tools")

    result = await tasks.create_app(request)

    assert result["pkg"] == "com.example.newapp"
    assert result["is_builtin"] is False


@pytest.mark.asyncio
async def test_create_app_rejects_duplicate_pkg(engine):
    request = AppCreate(pkg="com.android.chrome", name="Chrome Again", icon="public", category="browser")

    with pytest.raises(HTTPException) as exc_info:
        await tasks.create_app(request)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_app_returns_404_for_missing_pkg(engine):
    request = AppUpdate(name="X", icon="star", category="tools")

    with pytest.raises(HTTPException) as exc_info:
        await tasks.update_app("does.not.exist", request)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_app_updates_existing_row(engine):
    await tasks.create_app(AppCreate(pkg="com.example.newapp", name="Orig", icon="star", category="tools"))

    updated = await tasks.update_app(
        "com.example.newapp", AppUpdate(name="Renamed", icon="explore", category="tools")
    )

    assert updated["name"] == "Renamed"
    assert updated["icon"] == "explore"


@pytest.mark.asyncio
async def test_delete_app_returns_404_for_missing_pkg(engine):
    with pytest.raises(HTTPException) as exc_info:
        await tasks.delete_app("does.not.exist")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_app_succeeds_for_unreferenced_app(engine):
    await tasks.create_app(AppCreate(pkg="com.example.newapp", name="New App", icon="star", category="tools"))

    result = await tasks.delete_app("com.example.newapp")

    assert result == {"status": "deleted", "pkg": "com.example.newapp"}


@pytest.mark.asyncio
async def test_delete_app_returns_409_when_referenced_by_a_task_preset(engine):
    await tasks.create_task_preset(
        TaskPresetWrite(
            title="Uses Chrome",
            description="d",
            goal="g",
            profile="flash",
            app_pkgs=["com.android.chrome"],
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await tasks.delete_app("com.android.chrome")

    assert exc_info.value.status_code == 409
