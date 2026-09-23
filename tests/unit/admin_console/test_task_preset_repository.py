from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)


def _row(id_suffix="1", **overrides):
    row = {
        "id": f"task-{id_suffix}",
        "title": "Test Task",
        "description": "A test task",
        "goal": "Do the test thing",
        "profile": "flash",
        "category": "flash",
        "tag": "Test App",
        "apps": [
            {"name": "Test App", "pkg": "com.test.app", "category": "tools"}
        ],
        "required_packages": ["com.test.app"],
        "match_mode": "any",
        "priority": 60,
        "is_builtin": False,
        "created_at": "2026-09-22T00:00:00+00:00",
        "updated_at": "2026-09-22T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def test_create_and_list_round_trips_json_fields(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    created = repo.create(_row())

    assert created["id"] == "task-1"

    rows = repo.list_all()
    assert len(rows) == 1
    assert rows[0]["apps"] == [
        {"name": "Test App", "pkg": "com.test.app", "category": "tools"}
    ]
    assert rows[0]["required_packages"] == ["com.test.app"]
    assert rows[0]["is_builtin"] is False


def test_update_changes_fields_and_returns_full_row(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    repo.create(_row())

    updated = repo.update("task-1", {"title": "Renamed", "priority": 80})

    assert updated["title"] == "Renamed"
    assert updated["priority"] == 80
    assert updated["id"] == "task-1"


def test_update_missing_id_returns_none(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    assert repo.update("does-not-exist", {"title": "X"}) is None


def test_delete_returns_true_when_row_removed(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    repo.create(_row())

    assert repo.delete("task-1") is True
    assert repo.list_all() == []


def test_delete_missing_id_returns_false(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    assert repo.delete("does-not-exist") is False


def test_seed_if_empty_only_seeds_once(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    repo.seed_if_empty([_row("1"), _row("2")])
    assert len(repo.list_all()) == 2

    repo.seed_if_empty([_row("3")])
    assert len(repo.list_all()) == 2


def test_get_returns_none_for_missing_id(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    assert repo.get("does-not-exist") is None


def test_get_returns_existing_row(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    repo.create(_row())

    row = repo.get("task-1")

    assert row["title"] == "Test Task"
    assert row["apps"] == [
        {"name": "Test App", "pkg": "com.test.app", "category": "tools"}
    ]
