import pytest

from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.services.task_preset_catalog import TaskRecommendationEngine


def _engine(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    return TaskRecommendationEngine(repository=repo)


def test_get_all_tasks_seeds_the_builtin_presets(tmp_path):
    from apps.admin_console.services.task_preset_catalog import PRESET_TASK_CATALOG

    engine = _engine(tmp_path)

    tasks = engine.get_all_tasks()

    assert len(tasks) == len(PRESET_TASK_CATALOG)
    assert all(t["is_builtin"] is True for t in tasks)


def test_get_app_registry_returns_package_lookup(tmp_path):
    engine = _engine(tmp_path)

    registry = engine.get_app_registry()

    assert registry["com.android.chrome"]["name"] == "Chrome"


def test_recommend_tasks_prioritizes_device_matched_apps(tmp_path):
    engine = _engine(tmp_path)

    matched = engine.recommend_tasks(installed_packages=["com.android.chrome"], limit=20)

    ids_in_order = [t["id"] for t in matched]
    assert ids_in_order.index("chrome_research") < ids_in_order.index("maps_coffee")
    chrome_task = next(t for t in matched if t["id"] == "chrome_research")
    assert chrome_task["is_device_matched"] is True


def test_recommend_tasks_filters_by_category(tmp_path):
    engine = _engine(tmp_path)

    pro_tasks = engine.recommend_tasks(installed_packages=[], category="pro", limit=20)

    assert pro_tasks
    assert all(t["profile"] == "pro" for t in pro_tasks)


def test_create_task_derives_tag_and_category_for_multi_app(tmp_path):
    engine = _engine(tmp_path)

    created = engine.create_task(
        {
            "title": "My Task",
            "description": "desc",
            "goal": "goal",
            "profile": "pro",
            "app_pkgs": ["com.android.chrome", "com.google.android.keep"],
        }
    )

    assert created["category"] == "cross_app"
    assert created["tag"] == "Chrome + Keep Notes"
    assert created["required_packages"] == ["com.android.chrome", "com.google.android.keep"]
    assert created["is_builtin"] is False
    assert created["priority"] == 60


def test_create_task_rejects_unknown_package(tmp_path):
    engine = _engine(tmp_path)

    with pytest.raises(ValueError, match="com.unknown.app"):
        engine.create_task(
            {
                "title": "Bad",
                "description": "desc",
                "goal": "goal",
                "profile": "flash",
                "app_pkgs": ["com.unknown.app"],
            }
        )


def test_update_task_returns_none_for_missing_id(tmp_path):
    engine = _engine(tmp_path)

    result = engine.update_task(
        "does-not-exist",
        {
            "title": "X",
            "description": "d",
            "goal": "g",
            "profile": "flash",
            "app_pkgs": ["com.android.chrome"],
        },
    )

    assert result is None


def test_delete_task_removes_a_seeded_builtin(tmp_path):
    engine = _engine(tmp_path)
    engine.get_all_tasks()  # trigger seeding

    assert engine.delete_task("maps_coffee") is True
    remaining_ids = [t["id"] for t in engine.get_all_tasks()]
    assert "maps_coffee" not in remaining_ids
