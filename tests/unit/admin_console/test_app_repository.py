import sqlite3

from apps.admin_console.database.repositories.app_repository import AppRepository


def _row(pkg="com.test.app", **overrides):
    row = {
        "pkg": pkg,
        "name": "Test App",
        "category": "tools",
        "is_builtin": False,
        "created_at": "2026-09-22T00:00:00+00:00",
        "updated_at": "2026-09-22T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def test_create_and_list_round_trips_fields(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    created = repo.create(_row())

    assert created["pkg"] == "com.test.app"

    rows = repo.list_all()
    assert len(rows) == 1
    assert rows[0]["name"] == "Test App"
    assert rows[0]["is_builtin"] is False


def test_create_returns_none_for_duplicate_pkg(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    repo.create(_row())

    assert repo.create(_row(name="Different Name")) is None
    assert len(repo.list_all()) == 1


def test_get_returns_none_for_missing_pkg(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    assert repo.get("does.not.exist") is None


def test_get_returns_existing_row(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    repo.create(_row())

    row = repo.get("com.test.app")
    assert row["name"] == "Test App"


def test_update_changes_fields_and_returns_full_row(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    repo.create(_row())

    updated = repo.update("com.test.app", {"name": "Renamed"})

    assert updated["name"] == "Renamed"
    assert updated["pkg"] == "com.test.app"


def test_update_missing_pkg_returns_none(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    assert repo.update("does.not.exist", {"name": "X"}) is None


def test_delete_returns_true_when_row_removed(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    repo.create(_row())

    assert repo.delete("com.test.app") is True
    assert repo.list_all() == []


def test_delete_missing_pkg_returns_false(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    assert repo.delete("does.not.exist") is False


def test_ensure_table_migrates_away_a_pre_existing_icon_column(tmp_path):
    """A table created before `icon` was removed still has it NOT NULL --
    _ensure_table() must drop it so inserts without `icon` still succeed."""
    db_path = tmp_path / "apps.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE apps (
            pkg TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            is_builtin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO apps VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("com.old.app", "Old App", "star", "tools", 0, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    repo = AppRepository(db_path)
    created = repo.create(_row("com.new.app"))

    assert created["pkg"] == "com.new.app"
    rows = repo.list_all()
    assert len(rows) == 2
    assert "icon" not in rows[0]


def test_seed_if_empty_only_seeds_once(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    repo.seed_if_empty([_row("com.test.app1"), _row("com.test.app2")])
    assert len(repo.list_all()) == 2

    repo.seed_if_empty([_row("com.test.app3")])
    assert len(repo.list_all()) == 2
