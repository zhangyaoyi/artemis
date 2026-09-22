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


def _seed_curated_preset(engine):
    """Seed a preset directly via the repository with hand-curated
    category/priority/match_mode values that differ from what
    `_derive_fields` (create_task's logic) would compute. This mirrors a
    real built-in preset like `pro_settings_qa` (category="monitor"), but
    also pins match_mode="all" so we can confirm it survives an update
    untouched -- create_task's derivation always forces match_mode="any",
    so this value could only have come from curation.
    """
    engine._ensure_seeded()
    now = "2026-01-01T00:00:00+00:00"
    row = {
        "id": "curated_preset",
        "title": "Original Title",
        "description": "Original description",
        "goal": "Original goal",
        "profile": "pro",
        "category": "monitor",
        "tag": "Chrome",
        "apps": [
            {"name": "Chrome", "icon": "public", "pkg": "com.android.chrome", "category": "browser"}
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


def test_update_task_preserves_category_priority_and_match_mode_on_noop_edit(tmp_path):
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
    # _derive_fields (which would give category="pro", match_mode="any",
    # priority=60).
    assert updated["category"] == "monitor"
    assert updated["match_mode"] == "all"
    assert updated["priority"] == 93


def test_update_task_recomputes_tag_and_required_packages_when_apps_change(tmp_path):
    """When the app selection legitimately changes, tag/apps/required_packages
    must update to reflect the new selection. Per the judgment call documented
    in TaskRecommendationEngine.update_task, category/match_mode/priority are
    still preserved from the existing row even when the app selection changes
    from single-app to multi-app -- update_task never recomputes those fields,
    only create_task does. This is a deliberate choice: category/match_mode/
    priority are curated properties of a preset, not a mechanical function of
    the app count, so an edit shouldn't silently flip them (e.g. a
    single-app "monitor" preset gaining a second app should not silently
    become an uncurated "cross_app" preset with default priority)."""
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
    # Category/match_mode/priority remain preserved -- see docstring above.
    assert updated["category"] == "monitor"
    assert updated["match_mode"] == "all"
    assert updated["priority"] == 93


def test_create_task_still_derives_category_match_mode_and_priority_fresh(tmp_path):
    """Sanity check that create_task's behavior is unchanged by the
    _derive_fields/_derive_app_fields split: brand-new presets still get
    category derived from app count/profile, match_mode="any", and
    priority=60."""
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

    assert created["category"] == "flash"
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
        {"pkg": "com.example.newapp", "name": "New App", "icon": "star", "category": "tools"}
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


def test_create_app_returns_none_for_duplicate_pkg(tmp_path):
    engine = _engine(tmp_path)
    engine.create_app({"pkg": "com.example.newapp", "name": "New App", "icon": "star", "category": "tools"})

    assert (
        engine.create_app(
            {"pkg": "com.example.newapp", "name": "Different", "icon": "star", "category": "tools"}
        )
        is None
    )


def test_update_app_returns_none_for_missing_pkg(tmp_path):
    engine = _engine(tmp_path)

    assert engine.update_app("does.not.exist", {"name": "X", "icon": "star", "category": "tools"}) is None


def test_update_app_changes_name_icon_category(tmp_path):
    engine = _engine(tmp_path)
    engine.create_app({"pkg": "com.example.newapp", "name": "Orig", "icon": "star", "category": "tools"})

    updated = engine.update_app(
        "com.example.newapp", {"name": "Renamed", "icon": "explore", "category": "tools"}
    )

    assert updated["name"] == "Renamed"
    assert updated["icon"] == "explore"


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
