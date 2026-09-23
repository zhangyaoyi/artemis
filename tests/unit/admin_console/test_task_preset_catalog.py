import pytest

from apps.admin_console.database.repositories.app_repository import AppRepository
from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.services.task_preset_catalog import TaskRecommendationEngine


def _engine(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    apps_repo = AppRepository(tmp_path / "apps.db")
    return TaskRecommendationEngine(repository=repo, app_repository=apps_repo)


def test_get_all_tasks_seeds_the_builtin_presets(tmp_path):
    from apps.admin_console.services.task_preset_catalog import PRESET_TASK_CATALOG

    engine = _engine(tmp_path)

    tasks = engine.get_all_tasks()

    assert len(tasks) == len(PRESET_TASK_CATALOG)
    assert all(t["is_builtin"] is True for t in tasks)
    assert all(t["category"] == t["apps"][0]["category"] for t in tasks)


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

    browser_tasks = engine.recommend_tasks(
        installed_packages=[], category="browser", limit=20
    )

    assert browser_tasks
    assert all(t["category"] == "browser" for t in browser_tasks)
    assert {t["profile"] for t in browser_tasks} == {"flash", "pro"}


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

    assert created["category"] == "browser"
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


def _seed_curated_preset(engine):
    """Seed a preset directly via the repository with hand-curated
    priority/match_mode values that differ from what `_derive_fields`
    (create_task's logic) would compute. It pins match_mode="all" so we
    can confirm it survives an update untouched -- create_task's derivation
    always forces match_mode="any", so this value could only have come from
    curation.
    """
    engine._ensure_seeded()
    now = "2026-01-01T00:00:00+00:00"
    row = {
        "id": "curated_preset",
        "title": "Original Title",
        "description": "Original description",
        "goal": "Original goal",
        "profile": "pro",
        "category": "browser",
        "tag": "Chrome",
        "apps": [
            {"name": "Chrome", "pkg": "com.android.chrome", "category": "browser"}
        ],
        "required_packages": ["com.android.chrome"],
        "match_mode": "all",
        "priority": 93,
        "is_builtin": True,
        "created_at": now,
        "updated_at": now,
    }
    engine.repository.create(row)
    return row


def test_update_task_preserves_priority_and_match_mode_on_noop_edit(tmp_path):
    """Finding 1 regression test: a title-only edit must not clobber the
    existing preset's curated category/priority/match_mode."""
    engine = _engine(tmp_path)
    _seed_curated_preset(engine)

    updated = engine.update_task(
        "curated_preset",
        {
            "title": "Renamed Title",
            "description": "Original description",
            "goal": "Original goal",
            "profile": "pro",
            "app_pkgs": ["com.android.chrome"],
        },
    )

    assert updated is not None
    assert updated["title"] == "Renamed Title"
    # These must be UNCHANGED from the seeded values, not recomputed via
    # _derive_fields (which would reset match_mode/priority).
    assert updated["category"] == "browser"
    assert updated["match_mode"] == "all"
    assert updated["priority"] == 93


def test_update_task_recomputes_tag_and_required_packages_when_apps_change(tmp_path):
    """When the app selection legitimately changes, tag/apps/required_packages
    and category must update to reflect the new selection. Match mode and
    priority remain curated properties and should not silently reset."""
    engine = _engine(tmp_path)
    _seed_curated_preset(engine)

    updated = engine.update_task(
        "curated_preset",
        {
            "title": "Original Title",
            "description": "Original description",
            "goal": "Original goal",
            "profile": "pro",
            "app_pkgs": ["com.android.chrome", "com.google.android.keep"],
        },
    )

    assert updated is not None
    assert updated["tag"] == "Chrome + Keep Notes"
    assert updated["required_packages"] == ["com.android.chrome", "com.google.android.keep"]
    assert len(updated["apps"]) == 2
    # The first app remains Chrome, so the domain remains browser.
    assert updated["category"] == "browser"
    assert updated["match_mode"] == "all"
    assert updated["priority"] == 93


def test_update_task_uses_new_first_app_category(tmp_path):
    engine = _engine(tmp_path)
    _seed_curated_preset(engine)

    updated = engine.update_task(
        "curated_preset",
        {
            "title": "Original Title",
            "description": "Original description",
            "goal": "Original goal",
            "profile": "pro",
            "app_pkgs": ["com.google.android.apps.maps", "com.android.chrome"],
        },
    )

    assert updated is not None
    assert updated["category"] == "navigation"
    assert updated["match_mode"] == "all"
    assert updated["priority"] == 93


def test_existing_task_category_is_migrated_from_app_registry(tmp_path):
    engine = _engine(tmp_path)
    now = "2026-01-01T00:00:00+00:00"
    engine.repository.create(
        {
            "id": "legacy-task",
            "title": "Legacy",
            "description": "Legacy category",
            "goal": "g",
            "profile": "flash",
            "category": "flash",
            "tag": "WeChat",
            "apps": [
                {"name": "WeChat", "pkg": "com.tencent.mm", "category": "social"}
            ],
            "required_packages": ["com.tencent.mm"],
            "match_mode": "any",
            "priority": 60,
            "is_builtin": False,
            "created_at": now,
            "updated_at": now,
        }
    )

    tasks = engine.get_all_tasks()

    assert tasks[0]["category"] == "social"


def test_create_task_derives_first_app_category_match_mode_and_priority(tmp_path):
    engine = _engine(tmp_path)

    created = engine.create_task(
        {
            "title": "Single App Task",
            "description": "desc",
            "goal": "goal",
            "profile": "flash",
            "app_pkgs": ["com.android.chrome"],
        }
    )

    assert created["category"] == "browser"
    assert created["match_mode"] == "any"
    assert created["priority"] == 60


def test_get_apps_seeds_the_builtin_app_registry(tmp_path):
    from apps.admin_console.services.task_preset_catalog import APP_REGISTRY

    engine = _engine(tmp_path)

    apps = engine.get_apps()

    assert len(apps) == len(APP_REGISTRY)
    assert all(a["is_builtin"] is True for a in apps)


def test_get_app_registry_returns_legacy_dict_shape(tmp_path):
    engine = _engine(tmp_path)

    registry = engine.get_app_registry()

    assert registry["com.android.chrome"]["name"] == "Chrome"


def test_create_app_adds_a_new_selectable_app(tmp_path):
    engine = _engine(tmp_path)

    created = engine.create_app(
        {"pkg": "com.example.newapp", "name": "New App", "category": "tools"}
    )

    assert created["pkg"] == "com.example.newapp"
    assert created["is_builtin"] is False

    task = engine.create_task(
        {
            "title": "Use New App",
            "description": "d",
            "goal": "g",
            "profile": "flash",
            "app_pkgs": ["com.example.newapp"],
        }
    )
    assert task["required_packages"] == ["com.example.newapp"]
    assert task["category"] == "tools"


def test_create_app_returns_none_for_duplicate_pkg(tmp_path):
    engine = _engine(tmp_path)
    engine.create_app({"pkg": "com.example.newapp", "name": "New App", "category": "tools"})

    assert (
        engine.create_app(
            {"pkg": "com.example.newapp", "name": "Different", "category": "tools"}
        )
        is None
    )


def test_update_app_returns_none_for_missing_pkg(tmp_path):
    engine = _engine(tmp_path)

    assert engine.update_app("does.not.exist", {"name": "X", "category": "tools"}) is None


def test_update_app_changes_name_category(tmp_path):
    engine = _engine(tmp_path)
    engine.create_app({"pkg": "com.example.newapp", "name": "Orig", "category": "tools"})

    updated = engine.update_app(
        "com.example.newapp", {"name": "Renamed", "category": "tools"}
    )

    assert updated["name"] == "Renamed"


def test_update_app_category_cascades_to_first_app_tasks(tmp_path):
    engine = _engine(tmp_path)
    task = engine.create_task(
        {
            "title": "Use Chrome",
            "description": "d",
            "goal": "g",
            "profile": "flash",
            "app_pkgs": ["com.android.chrome"],
        }
    )

    engine.update_app("com.android.chrome", {"name": "Chrome", "category": "web"})

    assert engine.repository.get(task["id"])["category"] == "web"


def test_delete_app_succeeds_when_unreferenced(tmp_path):
    engine = _engine(tmp_path)
    engine.get_apps()  # trigger app seeding

    # com.google.android.calendar is not in any PRESET_TASK_CATALOG entry's
    # required_packages, so it's safe to delete.
    deleted, blocking = engine.delete_app("com.google.android.calendar")

    assert deleted is True
    assert blocking == 0


def test_delete_app_blocked_when_referenced_by_a_task_preset(tmp_path):
    engine = _engine(tmp_path)
    engine.get_all_tasks()  # trigger task seeding; "maps_coffee" references this pkg

    deleted, blocking = engine.delete_app("com.google.android.apps.maps")

    assert deleted is False
    assert blocking > 0


def test_resolve_apps_rejects_unknown_package_via_app_repository(tmp_path):
    engine = _engine(tmp_path)

    try:
        engine.create_task(
            {
                "title": "Bad",
                "description": "d",
                "goal": "g",
                "profile": "flash",
                "app_pkgs": ["com.totally.unknown"],
            }
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "com.totally.unknown" in str(exc)
