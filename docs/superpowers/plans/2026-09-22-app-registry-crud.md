# App Registry CRUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users add, edit, and delete apps in the "app registry" (the list of apps a Recommended Task preset can reference) from inside the task-creation modal, with the backend as the single source of truth, replacing the two hand-synced hardcoded copies of `APP_REGISTRY` (backend `task_preset_catalog.py`, frontend `smart-tasks.data.ts`).

**Architecture:** Same shape as the already-shipped Recommended Tasks CRUD feature, one layer down: a new `apps` SQLite table (bootstrapped the same lazy `CREATE TABLE IF NOT EXISTS` way as `task_presets`, seeded once from the current 22-entry registry), a new `AppRepository`, four new REST endpoints (`GET`/`POST`/`PUT`/`DELETE /api/apps`), and a new frontend `AppRegistryService`. `TaskRecommendationEngine`'s existing app-package validation switches from the static `APP_REGISTRY` dict to querying `AppRepository`. `TaskPresetFormComponent`'s app picker gains inline add/edit/delete controls on each chip plus a trailing "+ Add App" chip — no new page, no new modal-on-modal.

**Tech Stack:** FastAPI + Pydantic + sqlite3 (backend, `apps/admin_console`), Angular 17+ standalone components + signals + `HttpClient` (frontend, `apps/showcase_ui`), pytest (`pytest-asyncio` for router tests). `ng test` cannot execute in the sandbox this plan may be implemented in (headless Chrome cannot load any page there, including `about:blank`'s real siblings — confirmed during the prior plan's execution) — if that's still true, follow the same adaptation used last time: `ng build` as the compile-check gate plus a rigorous manual trace of each spec's assertions, called out explicitly in every frontend task's report.

**Spec:** `docs/superpowers/specs/2026-09-22-app-registry-crud-design.md`

## Global Constraints

- Backend is the single source of truth for the app registry; both hardcoded copies (`APP_REGISTRY` in `task_preset_catalog.py` and in `smart-tasks.data.ts`) are deleted.
- The 22 built-in apps become ordinary, fully editable/deletable rows once seeded (`is_builtin` is a display hint only, same treatment as task presets — never a permission gate).
- `pkg` (package name) is required, free-text, user-typed, never validated against real device data, and immutable once an app is created.
- Icon selection is a fixed frontend-only dropdown of ~20 Material Symbols names (seeded from icons already in use) — this list itself stays static, unlike the app registry.
- Deleting an app referenced by any task preset's `required_packages` is blocked (409 with a reference count), never silently allowed or cascaded.
- Entry point for app management is inline inside `TaskPresetFormComponent`'s existing app picker — no separate page.

---

### Task 1: `AppRepository` (backend persistence)

**Files:**
- Create: `apps/admin_console/database/repositories/app_repository.py`
- Test: `tests/unit/admin_console/test_app_repository.py`

**Interfaces:**
- Consumes: `apps.admin_console.database.connection.db_session(db_path)` (existing context manager, same one `TaskPresetRepository` uses).
- Produces: `AppRepository` with `list_all() -> list[dict]`, `get(pkg: str) -> dict | None`, `create(row: dict) -> dict | None` (returns `None` if `pkg` already exists), `update(pkg: str, fields: dict) -> dict | None` (returns `None` if `pkg` doesn't exist), `delete(pkg: str) -> bool`, `seed_if_empty(rows: list[dict]) -> None`; and the module-level singleton `app_repository = AppRepository()`. Row dicts always have keys: `pkg, name, icon, category, is_builtin, created_at, updated_at`, with `is_builtin` as a Python `bool`. Task 2 consumes this.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_app_repository.py`:

```python
from apps.admin_console.database.repositories.app_repository import AppRepository


def _row(pkg="com.test.app", **overrides):
    row = {
        "pkg": pkg,
        "name": "Test App",
        "icon": "star",
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

    updated = repo.update("com.test.app", {"name": "Renamed", "icon": "explore"})

    assert updated["name"] == "Renamed"
    assert updated["icon"] == "explore"
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


def test_seed_if_empty_only_seeds_once(tmp_path):
    repo = AppRepository(tmp_path / "apps.db")
    repo.seed_if_empty([_row("com.test.app1"), _row("com.test.app2")])
    assert len(repo.list_all()) == 2

    repo.seed_if_empty([_row("com.test.app3")])
    assert len(repo.list_all()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_app_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.admin_console.database.repositories.app_repository'`

- [ ] **Step 3: Implement `AppRepository`**

Create `apps/admin_console/database/repositories/app_repository.py`:

```python
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SQLite-backed repository for the user-editable app registry."""

import sqlite3
from typing import Any

try:
    from admin_console.database.connection import db_session
except ImportError:
    from apps.admin_console.database.connection import db_session


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS apps (
    pkg TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_COLUMNS = [
    "pkg",
    "name",
    "icon",
    "category",
    "is_builtin",
    "created_at",
    "updated_at",
]


class AppRepository:
    """Repository for the user-editable app registry (Recommended Tasks' app picker)."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_TABLE_SQL)

    @staticmethod
    def _encode_value(column: str, value: Any) -> Any:
        if column == "is_builtin":
            return 1 if value else 0
        return value

    @classmethod
    def _encode_values(cls, row: dict[str, Any], columns: list[str]) -> list[Any]:
        return [cls._encode_value(c, row[c]) for c in columns]

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["is_builtin"] = bool(d["is_builtin"])
        return d

    def list_all(self) -> list[dict[str, Any]]:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            cursor = conn.execute("SELECT * FROM apps ORDER BY name ASC")
            return [self._decode_row(row) for row in cursor.fetchall()]

    def get(self, pkg: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            row = conn.execute("SELECT * FROM apps WHERE pkg = ?", (pkg,)).fetchone()
        return self._decode_row(row) if row else None

    def create(self, row: dict[str, Any]) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            existing = conn.execute("SELECT 1 FROM apps WHERE pkg = ?", (row["pkg"],)).fetchone()
            if existing:
                return None
            conn.execute(
                f"INSERT INTO apps ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                self._encode_values(row, _COLUMNS),
            )
            conn.commit()
        return {**row}

    def update(self, pkg: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        settable = [c for c in _COLUMNS if c in fields and c not in ("pkg", "is_builtin", "created_at")]
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            if settable:
                assignments = ", ".join(f"{c} = ?" for c in settable)
                values = self._encode_values(fields, settable)
                values.append(pkg)
                cursor = conn.execute(
                    f"UPDATE apps SET {assignments} WHERE pkg = ?", values
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return None
            row = conn.execute("SELECT * FROM apps WHERE pkg = ?", (pkg,)).fetchone()
        return self._decode_row(row) if row else None

    def delete(self, pkg: str) -> bool:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            cursor = conn.execute("DELETE FROM apps WHERE pkg = ?", (pkg,))
            conn.commit()
            return cursor.rowcount > 0

    def seed_if_empty(self, rows: list[dict[str, Any]]) -> None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            existing = conn.execute("SELECT COUNT(*) AS n FROM apps").fetchone()["n"]
            if existing > 0:
                return
            for row in rows:
                conn.execute(
                    f"INSERT OR IGNORE INTO apps ({', '.join(_COLUMNS)}) "
                    f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                    self._encode_values(row, _COLUMNS),
                )
            conn.commit()


app_repository = AppRepository()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_app_repository.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/admin_console/database/repositories/app_repository.py tests/unit/admin_console/test_app_repository.py
git commit -m "feat: add AppRepository for app registry persistence"
```

---

### Task 2: `TaskRecommendationEngine` gains app-registry CRUD and repository-backed app validation

**Files:**
- Modify: `apps/admin_console/services/task_preset_catalog.py`
- Modify: `tests/unit/admin_console/test_task_preset_catalog.py` (existing `_engine(tmp_path)` helper needs a second repository)
- Modify: `tests/unit/admin_console/test_task_preset_endpoints.py` (existing `engine` fixture needs a second repository)

**Interfaces:**
- Consumes: `AppRepository` from Task 1 (`list_all`, `get`, `create`, `update`, `delete`, `seed_if_empty`), the existing module-level `APP_REGISTRY: dict[str, dict[str, str]]` (still the seed source — unchanged, only its *consumer* changes), and `PRESET_TASK_CATALOG`.
- Produces: `TaskRecommendationEngine(repository: TaskPresetRepository | None = None, app_repository: AppRepository | None = None)` with everything it already has, plus:
  - `get_apps() -> list[dict]` — new, full app rows for `GET /api/apps`.
  - `get_app_registry() -> dict[str, dict[str, str]]` — same legacy shape as before, now sourced from `AppRepository`.
  - `create_app(payload: dict) -> dict | None` — `payload` has `pkg, name, icon, category`; returns `None` if `pkg` already exists.
  - `update_app(pkg: str, payload: dict) -> dict | None` — `payload` has `name, icon, category`; returns `None` if `pkg` doesn't exist.
  - `delete_app(pkg: str) -> tuple[bool, int]` — `(deleted, blocking_count)`. `blocking_count > 0` means the delete was refused because that many task presets still reference `pkg`; in that case `deleted` is always `False`.
  - `_resolve_apps` (used by `create_task`/`update_task`) now validates against `AppRepository` instead of the static dict — Task 3's router doesn't need to change for this, it's transparent.

Task 3 consumes `get_apps`, `create_app`, `update_app`, `delete_app`.

- [ ] **Step 1: Write the failing tests**

Add these to the end of `tests/unit/admin_console/test_task_preset_catalog.py` (after the existing tests — do not remove anything already there):

```python
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
```

Then update the existing `_engine(tmp_path)` helper near the top of the same file. Change:

```python
def _engine(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    return TaskRecommendationEngine(repository=repo)
```

to:

```python
def _engine(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    apps_repo = AppRepository(tmp_path / "apps.db")
    return TaskRecommendationEngine(repository=repo, app_repository=apps_repo)
```

And add the import at the top of the file, alongside the existing `TaskPresetRepository` import:

```python
from apps.admin_console.database.repositories.app_repository import AppRepository
```

This is important beyond style: without it, every test in this file that calls `create_task`/`update_task` (which validate `app_pkgs` against the app repository) would silently fall back to the real, global `app_repository` singleton — writing seed data into the actual production SQLite database as a side effect of running unit tests. Passing an isolated `tmp_path`-backed `AppRepository` keeps these tests fully isolated, exactly like `TaskPresetRepository` already is.

- [ ] **Step 2: Update `test_task_preset_endpoints.py`'s fixture the same way**

In `tests/unit/admin_console/test_task_preset_endpoints.py`, add the same import:

```python
from apps.admin_console.database.repositories.app_repository import AppRepository
```

And change the `engine` fixture from:

```python
@pytest.fixture
def engine(tmp_path, monkeypatch):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    test_engine = TaskRecommendationEngine(repository=repo)
    monkeypatch.setattr(tasks, "task_recommendation_engine", test_engine)
    return test_engine
```

to:

```python
@pytest.fixture
def engine(tmp_path, monkeypatch):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    apps_repo = AppRepository(tmp_path / "apps.db")
    test_engine = TaskRecommendationEngine(repository=repo, app_repository=apps_repo)
    monkeypatch.setattr(tasks, "task_recommendation_engine", test_engine)
    return test_engine
```

Same reasoning as Step 1 — this file's tests call `create_task_preset`, which validates `app_pkgs` against the app repository; without this change they'd hit the real database.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_catalog.py tests/unit/admin_console/test_task_preset_endpoints.py -v`
Expected: FAIL — `TypeError: TaskRecommendationEngine.__init__() got an unexpected keyword argument 'app_repository'`, and `AttributeError`/`ImportError` for `get_apps`/`create_app`/etc. not existing yet.

- [ ] **Step 4: Add the `AppRepository` import to `task_preset_catalog.py`**

In `apps/admin_console/services/task_preset_catalog.py`, add this import block directly below the existing `TaskPresetRepository` try/except import block (i.e. right after its `except ImportError:` branch closes):

```python
try:
    from admin_console.database.repositories.app_repository import (
        AppRepository,
        app_repository as default_app_repository,
    )
except ImportError:
    from apps.admin_console.database.repositories.app_repository import (
        AppRepository,
        app_repository as default_app_repository,
    )
```

(The singleton is imported under the alias `default_app_repository` specifically to avoid clashing with the `app_repository` constructor parameter name added below.)

- [ ] **Step 5: Replace the `TaskRecommendationEngine` class and its trailing helpers**

Replace everything from `def _builtin_seed_rows() -> list[dict[str, Any]]:` through the final `task_recommendation_engine = TaskRecommendationEngine()` line (the whole tail of the file) with:

```python
def _builtin_seed_rows() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for task in PRESET_TASK_CATALOG:
        row = task.model_dump()
        row["is_builtin"] = True
        row["created_at"] = now
        row["updated_at"] = now
        rows.append(row)
    return rows


def _builtin_app_seed_rows() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for pkg, info in APP_REGISTRY.items():
        rows.append(
            {
                "pkg": pkg,
                "name": info["name"],
                "icon": info["icon"],
                "category": info.get("category", "general"),
                "is_builtin": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    return rows


class TaskRecommendationEngine:
    """Intelligent recommendation engine matching device capabilities."""

    def __init__(
        self,
        repository: TaskPresetRepository | None = None,
        app_repository: AppRepository | None = None,
    ):
        self.repository = repository or task_preset_repository
        self.app_repository = app_repository or default_app_repository
        self._seeded = False
        self._apps_seeded = False

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        self.repository.seed_if_empty(_builtin_seed_rows())
        self._seeded = True

    def _ensure_apps_seeded(self) -> None:
        if self._apps_seeded:
            return
        self.app_repository.seed_if_empty(_builtin_app_seed_rows())
        self._apps_seeded = True

    def get_all_tasks(self) -> list[dict[str, Any]]:
        self._ensure_seeded()
        return self.repository.list_all()

    def get_app_registry(self) -> dict[str, dict[str, str]]:
        self._ensure_apps_seeded()
        return {
            row["pkg"]: {
                "name": row["name"],
                "icon": row["icon"],
                "category": row["category"],
            }
            for row in self.app_repository.list_all()
        }

    def get_apps(self) -> list[dict[str, Any]]:
        self._ensure_apps_seeded()
        return self.app_repository.list_all()

    def recommend_tasks(
        self, installed_packages: list[str] | set[str], category: str = "all", limit: int = 12
    ) -> list[dict[str, Any]]:
        self._ensure_seeded()
        pkgs_set = (
            set(installed_packages) if isinstance(installed_packages, list) else installed_packages
        ) or set()

        scored_tasks: list[tuple[int, dict[str, Any], bool]] = []

        for row in self.repository.list_all():
            required_packages = row["required_packages"]
            is_matched = False
            if pkgs_set:
                if not required_packages:
                    is_matched = True
                elif row["match_mode"] == "all":
                    is_matched = all(pkg in pkgs_set for pkg in required_packages)
                else:
                    is_matched = any(pkg in pkgs_set for pkg in required_packages)

            score = row["priority"]
            if pkgs_set:
                if is_matched:
                    score += 100
                    if len(required_packages) > 1 and row["match_mode"] == "all":
                        score += 30
                else:
                    score -= 40

            if category == "flash" and row["profile"] != "flash":
                continue
            elif category == "pro" and row["profile"] != "pro":
                continue
            elif category == "cross_app" and row["category"] != "cross_app":
                continue
            elif category == "monitor" and row["category"] != "monitor":
                continue

            scored_tasks.append((score, row, is_matched))

        scored_tasks.sort(key=lambda item: item[0], reverse=True)

        results: list[dict[str, Any]] = []
        for _, row, matched in scored_tasks[:limit]:
            d = dict(row)
            d["is_device_matched"] = matched
            results.append(d)

        return results

    def _resolve_apps(self, app_pkgs: list[str]) -> list[AppInfo]:
        self._ensure_apps_seeded()
        apps = []
        for pkg in app_pkgs:
            row = self.app_repository.get(pkg)
            if not row:
                raise ValueError(f"Unknown app package: {pkg}")
            apps.append(
                AppInfo(name=row["name"], icon=row["icon"], pkg=pkg, category=row.get("category", "general"))
            )
        return apps

    def _derive_app_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compute the fields that legitimately change whenever the app
        selection (or title/description/goal/profile) changes.

        These are always safe to recompute from the submitted payload, for
        both new presets (create_task) and edits to existing ones
        (update_task).
        """
        app_pkgs = payload["app_pkgs"]
        if not app_pkgs:
            raise ValueError("At least one app must be selected.")
        apps = self._resolve_apps(app_pkgs)
        profile = payload["profile"]
        tag = " + ".join(a.name for a in apps)
        return {
            "title": payload["title"],
            "description": payload["description"],
            "goal": payload["goal"],
            "profile": profile,
            "tag": tag,
            "apps": [a.model_dump() for a in apps],
            "required_packages": app_pkgs,
        }

    def _derive_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Full field set for a BRAND NEW preset (create_task only).

        In addition to the always-recomputed app fields, this derives
        `category`, `match_mode`, and `priority` from scratch, which is the
        correct behavior for a preset that doesn't exist yet. Editing an
        existing preset must NOT go through this recomputation -- see
        update_task, which only recomputes the app fields and leaves the
        existing row's category/match_mode/priority untouched.
        """
        fields = self._derive_app_fields(payload)
        app_pkgs = payload["app_pkgs"]
        category = "cross_app" if len(app_pkgs) > 1 else fields["profile"]
        fields.update(
            {
                "category": category,
                "match_mode": "any",
                "priority": 60,
            }
        )
        return fields

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_seeded()
        fields = self._derive_fields(payload)
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": str(uuid.uuid4()),
            **fields,
            "is_builtin": False,
            "created_at": now,
            "updated_at": now,
        }
        return self.repository.create(row)

    def update_task(self, preset_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_seeded()
        # Only recompute the fields that legitimately change when the app
        # selection/title/description/goal/profile are edited. Deliberately
        # do NOT recompute category/match_mode/priority here (unlike
        # create_task): those are curated per-preset (e.g. "all packages
        # required" semantics, a hand-tuned priority, a specific catalog
        # tab). Omitting them from `fields` means
        # TaskPresetRepository.update() leaves those columns untouched in
        # the database, so an edit -- even one that changes the app
        # selection -- preserves the existing row's category, match_mode,
        # and priority instead of silently resetting them.
        fields = self._derive_app_fields(payload)
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self.repository.update(preset_id, fields)

    def delete_task(self, preset_id: str) -> bool:
        self._ensure_seeded()
        return self.repository.delete(preset_id)

    def create_app(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_apps_seeded()
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "pkg": payload["pkg"],
            "name": payload["name"],
            "icon": payload["icon"],
            "category": payload.get("category") or "general",
            "is_builtin": False,
            "created_at": now,
            "updated_at": now,
        }
        return self.app_repository.create(row)

    def update_app(self, pkg: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_apps_seeded()
        fields = {
            "name": payload["name"],
            "icon": payload["icon"],
            "category": payload.get("category") or "general",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.app_repository.update(pkg, fields)

    def delete_app(self, pkg: str) -> tuple[bool, int]:
        """Delete an app unless a task preset still references it.

        Returns (deleted, blocking_count). blocking_count > 0 means the
        delete was refused because that many task presets still list this
        pkg in their required_packages.
        """
        self._ensure_seeded()
        referencing = [
            row for row in self.repository.list_all() if pkg in row["required_packages"]
        ]
        if referencing:
            return False, len(referencing)
        return self.app_repository.delete(pkg), 0


task_recommendation_engine = TaskRecommendationEngine()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_catalog.py tests/unit/admin_console/test_task_preset_endpoints.py tests/unit/admin_console/test_app_repository.py -v`
Expected: PASS (all tests, including the 9 new ones added in Step 1)

- [ ] **Step 7: Commit**

```bash
git add apps/admin_console/services/task_preset_catalog.py tests/unit/admin_console/test_task_preset_catalog.py tests/unit/admin_console/test_task_preset_endpoints.py
git commit -m "feat: back TaskRecommendationEngine's app validation with AppRepository"
```

---

### Task 3: App registry API endpoints

**Files:**
- Modify: `apps/admin_console/schemas/task_schema.py`
- Modify: `apps/admin_console/routers/tasks.py`
- Test: `tests/unit/admin_console/test_app_endpoints.py`

**Interfaces:**
- Consumes: `task_recommendation_engine.get_apps/create_app/update_app/delete_app` from Task 2.
- Produces: `GET /api/apps`, `POST /api/apps`, `PUT /api/apps/{pkg}`, `DELETE /api/apps/{pkg}` route handlers `get_apps`, `create_app`, `update_app`, `delete_app` in `apps/admin_console/routers/tasks.py`, importable by tests as `apps.admin_console.routers.tasks.get_apps` etc.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_app_endpoints.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_app_endpoints.py -v`
Expected: FAIL — `ImportError: cannot import name 'AppCreate' from 'apps.admin_console.schemas.task_schema'`

- [ ] **Step 3: Add the `AppCreate`/`AppUpdate` schemas**

In `apps/admin_console/schemas/task_schema.py`, append these two classes at the end of the file (after `TaskPresetWrite`):

```python
class AppCreate(BaseModel):
    pkg: str
    name: str
    icon: str
    category: str = "general"


class AppUpdate(BaseModel):
    name: str
    icon: str
    category: str = "general"
```

- [ ] **Step 4: Add the four endpoints to the router**

In `apps/admin_console/routers/tasks.py`, update both `try`/`except ImportError` import blocks to also import `AppCreate` and `AppUpdate`:

```python
try:
    from admin_console.core.state import state
    from admin_console.database.repositories.session_repository import session_repo
    from admin_console.schemas.task_schema import AppCreate, AppUpdate, RunRequest, TaskPresetWrite
    from admin_console.services.ipc_service import ipc_service
    from admin_console.services.model_service import model_service
    from admin_console.services.task_preset_catalog import task_recommendation_engine
    from admin_console.services.task_queue_service import task_queue_service
except ImportError:
    from apps.admin_console.core.state import state
    from apps.admin_console.database.repositories.session_repository import session_repo
    from apps.admin_console.schemas.task_schema import AppCreate, AppUpdate, RunRequest, TaskPresetWrite
    from apps.admin_console.services.ipc_service import ipc_service
    from apps.admin_console.services.model_service import model_service
    from apps.admin_console.services.task_preset_catalog import task_recommendation_engine
    from apps.admin_console.services.task_queue_service import task_queue_service
```

Then insert these four route handlers right after `delete_task_preset` (i.e. between the end of that function and the `@router.post("/api/run")` line):

```python
@router.get("/api/apps")
async def get_apps():
    """Retrieve the full user-editable app registry."""
    return task_recommendation_engine.get_apps()


@router.post("/api/apps")
async def create_app(request: AppCreate):
    """Add a new app to the registry."""
    created = task_recommendation_engine.create_app(request.model_dump())
    if created is None:
        raise HTTPException(status_code=409, detail=f"App '{request.pkg}' already exists.")
    return created


@router.put("/api/apps/{pkg}")
async def update_app(pkg: str, request: AppUpdate):
    """Update an existing app's name/icon/category."""
    updated = task_recommendation_engine.update_app(pkg, request.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail=f"App '{pkg}' not found.")
    return updated


@router.delete("/api/apps/{pkg}")
async def delete_app(pkg: str):
    """Delete an app from the registry, unless a task preset still references it."""
    deleted, blocking = task_recommendation_engine.delete_app(pkg)
    if blocking:
        raise HTTPException(status_code=409, detail=f"Used by {blocking} task preset(s).")
    if not deleted:
        raise HTTPException(status_code=404, detail=f"App '{pkg}' not found.")
    return {"status": "deleted", "pkg": pkg}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_app_endpoints.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Run the full admin_console test directory to confirm no regression**

Run: `uv run pytest tests/unit/admin_console -v`
Expected: All PASS (only the two pre-existing, unrelated `test_model_service.py` failures if your environment reproduces those — see the prior plan's ledger; they are not caused by this work)

- [ ] **Step 7: Commit**

```bash
git add apps/admin_console/schemas/task_schema.py apps/admin_console/routers/tasks.py tests/unit/admin_console/test_app_endpoints.py
git commit -m "feat: add app registry CRUD API endpoints"
```

---

### Task 4: Frontend `AppRegistryService`, and removing the static `APP_REGISTRY`

**Files:**
- Modify: `apps/showcase_ui/src/app/core/data/smart-tasks.data.ts` (full rewrite — short file)
- Modify: `apps/showcase_ui/src/app/core/services/task-recommendation.service.ts` (remove the now-dead `appRegistry` field and its import)
- Create: `apps/showcase_ui/src/app/core/services/app-registry.service.ts`
- Test: `apps/showcase_ui/src/app/core/services/app-registry.service.spec.ts`

**Interfaces:**
- Consumes: `GET /api/apps` (returns a bare JSON array, unlike `/api/tasks/catalog` which wraps in `{tasks: [...]}`), `POST /api/apps`, `PUT /api/apps/{pkg}`, `DELETE /api/apps/{pkg}` from Task 3.
- Produces: `AppRegistryService` with `apps: Signal<AppReference[]>`, `loadApps(): Observable<RawApp[]>`, `createApp(payload: AppWritePayload): Observable<AppReference>`, `updateApp(pkg: string, payload: AppUpdatePayload): Observable<AppReference>`, `deleteApp(pkg: string): Observable<{status: string; pkg: string}>`. Exported types `AppWritePayload = {pkg: string; name: string; icon: string; category: string}` and `AppUpdatePayload = {name: string; icon: string; category: string}`. Also produces `ICON_OPTIONS: string[]` (in `smart-tasks.data.ts`) and an `isBuiltin?: boolean` field on `AppReference`. Task 5 consumes all of this.

- [ ] **Step 1: Rewrite `smart-tasks.data.ts`**

Replace the full contents of `apps/showcase_ui/src/app/core/data/smart-tasks.data.ts` with:

```typescript
/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

export interface AppReference {
  name: string;
  icon: string;
  pkg?: string;
  category?: string;
  isBuiltin?: boolean;
}

export type SuggestionCategory =
  | 'all'
  | 'flash'
  | 'pro'
  | 'cross_app'
  | 'monitor';

export interface SmartSuggestion {
  id: string;
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  category: 'flash' | 'pro' | 'cross_app' | 'monitor';
  tag: string;
  apps: AppReference[];
  requiredPackages?: string[];
  matchMode?: 'any' | 'all';
  priority?: number;
  isBuiltin?: boolean;
}

/**
 * Fixed set of Material Symbols icon names offered when adding or editing
 * an app in the registry. This stays a static frontend list (unlike the
 * app registry itself, which is backend-owned) since it's UI-picker
 * metadata that only changes per-release, not per-user.
 */
export const ICON_OPTIONS: string[] = [
  'account_balance_wallet',
  'auto_stories',
  'calculate',
  'calendar_month',
  'chat',
  'explore',
  'forum',
  'headphones',
  'mail',
  'music_note',
  'note_alt',
  'photo_library',
  'public',
  'restaurant',
  'settings',
  'smart_display',
  'star',
  'storefront',
  'timer',
  'video_library'
];
```

This deletes the `APP_REGISTRY` constant entirely (the backend is now the source of truth for it) and adds `isBuiltin` to both `AppReference` and `SmartSuggestion` (the latter already existed from the prior plan — unchanged here) plus the new `ICON_OPTIONS` list.

- [ ] **Step 2: Remove the now-dead `appRegistry` field from `TaskRecommendationService`**

In `apps/showcase_ui/src/app/core/services/task-recommendation.service.ts`, change the import block from:

```typescript
import {
  AppReference,
  SmartSuggestion,
  SuggestionCategory,
  APP_REGISTRY
} from '../data/smart-tasks.data';
```

to:

```typescript
import {
  AppReference,
  SmartSuggestion,
  SuggestionCategory
} from '../data/smart-tasks.data';
```

(`AppReference` stays — it's still used by `RawTaskPreset.apps` and `mapPreset`.) Then delete this line entirely:

```typescript
  public readonly appRegistry = APP_REGISTRY;
```

This field's only consumer (`TaskPresetFormComponent`) switches to `AppRegistryService` in Task 5 — until Task 5 lands, `TaskPresetFormComponent` will fail to compile referencing this deleted field/import. That's expected and fixed in Task 5; don't touch `TaskPresetFormComponent` in this task.

- [ ] **Step 3: Write the failing service spec**

Create `apps/showcase_ui/src/app/core/services/app-registry.service.spec.ts`:

```typescript
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AppRegistryService } from './app-registry.service';

describe('AppRegistryService', () => {
  let service: AppRegistryService;
  let http: HttpTestingController;

  const rawApp = (overrides: Record<string, unknown> = {}) => ({
    pkg: 'com.android.chrome',
    name: 'Chrome',
    icon: 'public',
    category: 'browser',
    is_builtin: true,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AppRegistryService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(AppRegistryService);
    http = TestBed.inject(HttpTestingController);
    // The constructor eagerly loads the registry; drain that request first.
    http.expectOne('/api/apps').flush([]);
  });

  afterEach(() => http.verify());

  it('maps snake_case API fields to camelCase AppReference fields', () => {
    service.loadApps().subscribe();
    const req = http.expectOne('/api/apps');
    req.flush([rawApp()]);

    const loaded = service.apps();
    expect(loaded.length).toBe(1);
    expect(loaded[0].pkg).toBe('com.android.chrome');
    expect(loaded[0].isBuiltin).toBe(true);
  });

  it('creates an app then refreshes the list', () => {
    service.createApp({
      pkg: 'com.example.newapp',
      name: 'New App',
      icon: 'star',
      category: 'tools'
    }).subscribe();

    const createReq = http.expectOne('/api/apps');
    expect(createReq.request.method).toBe('POST');
    createReq.flush(rawApp({ pkg: 'com.example.newapp', name: 'New App' }));

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([rawApp({ pkg: 'com.example.newapp', name: 'New App' })]);

    expect(service.apps().map(a => a.pkg)).toEqual(['com.example.newapp']);
  });

  it('updates an app by pkg then refreshes the list', () => {
    service.updateApp('com.android.chrome', {
      name: 'Renamed',
      icon: 'public',
      category: 'browser'
    }).subscribe();

    const updateReq = http.expectOne('/api/apps/com.android.chrome');
    expect(updateReq.request.method).toBe('PUT');
    updateReq.flush(rawApp({ name: 'Renamed' }));

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([rawApp({ name: 'Renamed' })]);

    expect(service.apps()[0].name).toBe('Renamed');
  });

  it('deletes an app by pkg then refreshes the list', () => {
    service.deleteApp('com.android.chrome').subscribe();

    const deleteReq = http.expectOne('/api/apps/com.android.chrome');
    expect(deleteReq.request.method).toBe('DELETE');
    deleteReq.flush({ status: 'deleted', pkg: 'com.android.chrome' });

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([]);

    expect(service.apps()).toEqual([]);
  });
});
```

- [ ] **Step 4: Run the spec to verify it fails**

If `ng test` can run in your environment: `cd apps/showcase_ui && npx ng test --watch=false --include='**/app-registry.service.spec.ts'`, expect FAIL (module doesn't exist yet). If `ng test` cannot launch a browser in your sandbox (see the plan header), skip straight to Step 5 and rely on `ng build` plus a manual trace, exactly as the prior plan's Tasks 4-5 did — note this explicitly in your report.

- [ ] **Step 5: Implement `AppRegistryService`**

Create `apps/showcase_ui/src/app/core/services/app-registry.service.ts`:

```typescript
/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, tap } from 'rxjs';
import { AppReference } from '../data/smart-tasks.data';

export interface AppWritePayload {
  pkg: string;
  name: string;
  icon: string;
  category: string;
}

export interface AppUpdatePayload {
  name: string;
  icon: string;
  category: string;
}

interface RawApp {
  pkg: string;
  name: string;
  icon: string;
  category: string;
  is_builtin: boolean;
}

function mapApp(raw: RawApp): AppReference {
  return {
    pkg: raw.pkg,
    name: raw.name,
    icon: raw.icon,
    category: raw.category,
    isBuiltin: raw.is_builtin
  };
}

@Injectable({
  providedIn: 'root'
})
export class AppRegistryService {
  private http = inject(HttpClient);

  public apps = signal<AppReference[]>([]);

  constructor() {
    this.loadApps().subscribe();
  }

  /**
   * Fetches the full app registry from the backend and replaces `apps`.
   * Called on service init and after every mutation.
   */
  public loadApps(): Observable<RawApp[]> {
    return this.http.get<RawApp[]>('/api/apps').pipe(
      tap({
        next: (response) => this.apps.set(response.map(mapApp)),
        error: (err) => console.error('Failed to load app registry:', err)
      })
    );
  }

  public createApp(payload: AppWritePayload): Observable<AppReference> {
    return this.http.post<RawApp>('/api/apps', payload).pipe(
      tap(() => this.loadApps().subscribe()),
      map((raw) => mapApp(raw))
    );
  }

  public updateApp(pkg: string, payload: AppUpdatePayload): Observable<AppReference> {
    return this.http.put<RawApp>(`/api/apps/${pkg}`, payload).pipe(
      tap(() => this.loadApps().subscribe()),
      map((raw) => mapApp(raw))
    );
  }

  public deleteApp(pkg: string): Observable<{ status: string; pkg: string }> {
    return this.http.delete<{ status: string; pkg: string }>(`/api/apps/${pkg}`).pipe(
      tap(() => this.loadApps().subscribe())
    );
  }
}
```

- [ ] **Step 6: Verify**

If `ng test` works in your environment: `cd apps/showcase_ui && npx ng test --watch=false --include='**/app-registry.service.spec.ts'`, expect PASS (4 tests).

If not: `cd apps/showcase_ui && npx ng build`. Expect it to fail ONLY on `task-preset-form.component.ts` (which still references the now-deleted `TaskRecommendationService.appRegistry` field — that's Task 5's job to fix, not yours). Confirm no other file produces a new error, then do a manual trace: read `app-registry.service.spec.ts` and `app-registry.service.ts` together and confirm each assertion would pass. Write that trace into your report.

- [ ] **Step 7: Commit**

```bash
git add apps/showcase_ui/src/app/core/data/smart-tasks.data.ts apps/showcase_ui/src/app/core/services/task-recommendation.service.ts apps/showcase_ui/src/app/core/services/app-registry.service.ts apps/showcase_ui/src/app/core/services/app-registry.service.spec.ts
git commit -m "feat: add AppRegistryService, remove the static APP_REGISTRY"
```

---

### Task 5: Wire inline app management into `TaskPresetFormComponent`

**Files:**
- Modify: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.ts` (full rewrite)
- Modify: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.html` (full rewrite)
- Modify: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.scss` (full rewrite)
- Modify: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.spec.ts` (full rewrite)

**Interfaces:**
- Consumes: `AppRegistryService` from Task 4 (`apps` signal, `createApp`, `updateApp`, `deleteApp`, and the `AppWritePayload`/`AppUpdatePayload` types), `ICON_OPTIONS` from Task 4's `smart-tasks.data.ts`.
- Produces: same public `@Input`/`@Output` contract as before (`editingTask`, `errorText`, `save`, `cancel`) — unchanged, so Task 6 of the *prior* plan's `home.component.html` binding (`[editingTask]`, `(save)`, `(cancel)`) needs no changes.

- [ ] **Step 1: Rewrite the component TypeScript**

Replace the full contents of `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.ts` with:

```typescript
/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppReference, ICON_OPTIONS, SmartSuggestion } from '../../core/data/smart-tasks.data';
import { AppRegistryService, AppUpdatePayload, AppWritePayload } from '../../core/services/app-registry.service';
import { TaskPresetWritePayload } from '../../core/services/task-recommendation.service';

@Component({
  selector: 'app-task-preset-form',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './task-preset-form.component.html',
  styleUrl: './task-preset-form.component.scss'
})
export class TaskPresetFormComponent implements OnChanges {
  @Input() editingTask: SmartSuggestion | null = null;
  @Input() errorText: string | null = null;
  @Output() save = new EventEmitter<TaskPresetWritePayload>();
  @Output() cancel = new EventEmitter<void>();

  public appRegistryService = inject(AppRegistryService);
  public readonly iconOptions = ICON_OPTIONS;

  public title = signal<string>('');
  public description = signal<string>('');
  public goal = signal<string>('');
  public profile = signal<'flash' | 'pro'>('flash');
  public selectedPkgs = signal<Set<string>>(new Set());

  // Inline app-registry management (add/edit/delete an app from within
  // this modal's app picker).
  public showAppForm = signal<boolean>(false);
  public editingApp = signal<AppReference | null>(null);
  public appFormPkg = signal<string>('');
  public appFormName = signal<string>('');
  public appFormIcon = signal<string>(ICON_OPTIONS[0]);
  public appFormCategory = signal<string>('general');
  public appFormError = signal<string | null>(null);
  public appDeleteError = signal<string | null>(null);

  ngOnChanges(_changes: SimpleChanges): void {
    const task = this.editingTask;
    this.title.set(task?.title ?? '');
    this.description.set(task?.description ?? '');
    this.goal.set(task?.goal ?? '');
    this.profile.set(task?.profile ?? 'flash');
    this.selectedPkgs.set(new Set(task?.requiredPackages ?? []));
  }

  public isPkgSelected(pkg: string): boolean {
    return this.selectedPkgs().has(pkg);
  }

  public togglePkg(pkg: string): void {
    const next = new Set(this.selectedPkgs());
    if (next.has(pkg)) {
      next.delete(pkg);
    } else {
      next.add(pkg);
    }
    this.selectedPkgs.set(next);
  }

  public get isValid(): boolean {
    return (
      this.title().trim().length > 0 &&
      this.description().trim().length > 0 &&
      this.goal().trim().length > 0 &&
      this.selectedPkgs().size > 0
    );
  }

  public onSave(): void {
    if (!this.isValid) {
      return;
    }
    this.save.emit({
      title: this.title().trim(),
      description: this.description().trim(),
      goal: this.goal().trim(),
      profile: this.profile(),
      app_pkgs: Array.from(this.selectedPkgs())
    });
  }

  public onCancel(): void {
    this.cancel.emit();
  }

  // --- Inline app-registry management ---

  public openAddAppForm(): void {
    this.editingApp.set(null);
    this.appFormPkg.set('');
    this.appFormName.set('');
    this.appFormIcon.set(ICON_OPTIONS[0]);
    this.appFormCategory.set('general');
    this.appFormError.set(null);
    this.showAppForm.set(true);
  }

  public openEditAppForm(app: AppReference, event: Event): void {
    event.stopPropagation();
    this.editingApp.set(app);
    this.appFormPkg.set(app.pkg ?? '');
    this.appFormName.set(app.name);
    this.appFormIcon.set(app.icon);
    this.appFormCategory.set(app.category ?? 'general');
    this.appFormError.set(null);
    this.showAppForm.set(true);
  }

  public closeAppForm(): void {
    this.showAppForm.set(false);
    this.editingApp.set(null);
    this.appFormError.set(null);
  }

  public get isAppFormValid(): boolean {
    const pkgOk = this.editingApp() !== null || this.appFormPkg().trim().length > 0;
    return pkgOk && this.appFormName().trim().length > 0 && this.appFormIcon().trim().length > 0;
  }

  public saveApp(): void {
    if (!this.isAppFormValid) {
      return;
    }
    const editing = this.editingApp();
    const updatePayload: AppUpdatePayload = {
      name: this.appFormName().trim(),
      icon: this.appFormIcon(),
      category: this.appFormCategory().trim() || 'general'
    };
    const request$ = editing
      ? this.appRegistryService.updateApp(editing.pkg!, updatePayload)
      : this.appRegistryService.createApp({
          pkg: this.appFormPkg().trim(),
          ...updatePayload
        } as AppWritePayload);
    request$.subscribe({
      next: () => this.closeAppForm(),
      error: (err) => this.appFormError.set(err?.error?.detail || 'Failed to save app.')
    });
  }

  public deleteApp(app: AppReference, event: Event): void {
    event.stopPropagation();
    if (!app.pkg) {
      return;
    }
    this.appDeleteError.set(null);
    this.appRegistryService.deleteApp(app.pkg).subscribe({
      error: (err) => this.appDeleteError.set(err?.error?.detail || 'Failed to delete app.')
    });
  }
}
```

- [ ] **Step 2: Rewrite the component template**

Replace the full contents of `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.html` with:

```html
<div class="tpf-overlay" (click)="onCancel()">
  <div class="tpf-modal" (click)="$event.stopPropagation()">
    <div class="tpf-header">
      <h3>{{ editingTask ? 'Edit Task' : 'Add Task' }}</h3>
      <button type="button" class="tpf-close-btn" (click)="onCancel()">
        <span class="material-symbols-outlined">close</span>
      </button>
    </div>

    <div class="tpf-body">
      <label class="tpf-field">
        <span class="tpf-label">Title</span>
        <input type="text" [ngModel]="title()" (ngModelChange)="title.set($event)" placeholder="e.g. Find Specialty Coffee" />
      </label>

      <label class="tpf-field">
        <span class="tpf-label">Description</span>
        <input type="text" [ngModel]="description()" (ngModelChange)="description.set($event)" placeholder="Short summary shown on the card" />
      </label>

      <label class="tpf-field">
        <span class="tpf-label">Goal Prompt</span>
        <textarea rows="3" [ngModel]="goal()" (ngModelChange)="goal.set($event)" placeholder="The instruction sent to the agent"></textarea>
      </label>

      <div class="tpf-field">
        <span class="tpf-label">Profile</span>
        <div class="tpf-profile-toggle">
          <button type="button" [class.active]="profile() === 'flash'" (click)="profile.set('flash')">Flash</button>
          <button type="button" [class.active]="profile() === 'pro'" (click)="profile.set('pro')">Pro</button>
        </div>
      </div>

      <div class="tpf-field">
        <span class="tpf-label">Apps</span>
        @if (appDeleteError()) {
          <span class="tpf-inline-error">{{ appDeleteError() }}</span>
        }
        <div class="tpf-app-chips">
          @for (app of appRegistryService.apps(); track app.pkg) {
            <div class="tpf-app-chip-wrap">
              <button
                type="button"
                class="tpf-app-chip"
                [class.selected]="isPkgSelected(app.pkg!)"
                (click)="togglePkg(app.pkg!)"
              >
                <span class="material-symbols-outlined">{{ app.icon }}</span>
                <span>{{ app.name }}</span>
              </button>
              <div class="tpf-chip-actions">
                <button type="button" class="tpf-chip-action-btn" title="Edit app" (click)="openEditAppForm(app, $event)">
                  <span class="material-symbols-outlined">edit</span>
                </button>
                <button type="button" class="tpf-chip-action-btn tpf-chip-action-danger" title="Delete app" (click)="deleteApp(app, $event)">
                  <span class="material-symbols-outlined">delete</span>
                </button>
              </div>
            </div>
          }
          <button type="button" class="tpf-app-chip tpf-add-app-chip" (click)="openAddAppForm()">
            <span class="material-symbols-outlined">add</span>
            <span>Add App</span>
          </button>
        </div>

        @if (showAppForm()) {
          <div class="tpf-app-mini-form">
            @if (!editingApp()) {
              <input type="text" [ngModel]="appFormPkg()" (ngModelChange)="appFormPkg.set($event)" placeholder="Package name, e.g. com.example.app" />
            }
            <input type="text" [ngModel]="appFormName()" (ngModelChange)="appFormName.set($event)" placeholder="App name" />
            <select [ngModel]="appFormIcon()" (ngModelChange)="appFormIcon.set($event)">
              @for (icon of iconOptions; track icon) {
                <option [value]="icon">{{ icon }}</option>
              }
            </select>
            <input type="text" [ngModel]="appFormCategory()" (ngModelChange)="appFormCategory.set($event)" placeholder="Category (optional)" />
            @if (appFormError()) {
              <span class="tpf-inline-error">{{ appFormError() }}</span>
            }
            <div class="tpf-mini-actions">
              <button type="button" class="tpf-btn-secondary" (click)="closeAppForm()">Cancel</button>
              <button type="button" class="tpf-btn-primary" [disabled]="!isAppFormValid" (click)="saveApp()">{{ editingApp() ? 'Save' : 'Add' }}</button>
            </div>
          </div>
        }
      </div>
    </div>

    <div class="tpf-footer">
      @if (errorText) {
        <span class="tpf-error">{{ errorText }}</span>
      }
      <div class="tpf-footer-actions">
        <button type="button" class="tpf-btn-secondary" (click)="onCancel()">Cancel</button>
        <button type="button" class="tpf-btn-primary" [disabled]="!isValid" (click)="onSave()">Save</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Rewrite the component styles**

Replace the full contents of `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.scss` with:

```scss
.tpf-overlay {
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

.tpf-modal {
  width: 100%;
  max-width: 460px;
  max-height: 88vh;
  overflow-y: auto;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 20px 48px -12px rgba(15, 23, 42, 0.35);
  display: flex;
  flex-direction: column;
}

.tpf-header {
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

  .tpf-close-btn {
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

.tpf-body {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tpf-field {
  display: flex;
  flex-direction: column;
  gap: 6px;

  .tpf-label {
    font-size: 12px;
    font-weight: 600;
    color: #475569;
  }

  input,
  textarea,
  select {
    border: 1px solid rgba(203, 213, 225, 0.9);
    border-radius: 10px;
    padding: 8px 10px;
    font-size: 13px;
    font-family: inherit;
    color: #0f172a;
    resize: vertical;
    background: #ffffff;

    &:focus {
      outline: none;
      border-color: #1a73e8;
      box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }
  }
}

.tpf-profile-toggle {
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

.tpf-app-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 6px;
  max-height: 160px;
  overflow-y: auto;
  padding-top: 4px;
}

.tpf-app-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(203, 213, 225, 0.9);
  background: #ffffff;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;

  span.material-symbols-outlined {
    font-size: 14px;
  }

  &.selected {
    background: rgba(26, 115, 232, 0.1);
    border-color: rgba(26, 115, 232, 0.4);
    color: #1a73e8;
  }
}

.tpf-app-chip-wrap {
  position: relative;
  display: inline-flex;

  .tpf-chip-actions {
    position: absolute;
    top: -6px;
    right: -6px;
    display: flex;
    gap: 2px;
    opacity: 0;
    transition: opacity 0.15s ease;

    .tpf-chip-action-btn {
      width: 18px;
      height: 18px;
      border-radius: 6px;
      border: 1px solid rgba(203, 213, 225, 0.9);
      background: #ffffff;
      color: #475569;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      padding: 0;

      span {
        font-size: 11px;
      }

      &:hover {
        border-color: rgba(26, 115, 232, 0.4);
        color: #1a73e8;
      }

      &.tpf-chip-action-danger:hover {
        border-color: rgba(220, 38, 38, 0.4);
        color: #dc2626;
      }
    }
  }

  &:hover .tpf-chip-actions {
    opacity: 1;
  }
}

.tpf-add-app-chip {
  border-style: dashed;
  color: #64748b;

  &:hover {
    border-color: rgba(26, 115, 232, 0.55);
    color: #1a73e8;
  }
}

.tpf-app-mini-form {
  margin-top: 10px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid rgba(203, 213, 225, 0.9);
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 8px;

  .tpf-mini-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
}

.tpf-inline-error {
  display: block;
  color: #dc2626;
  font-size: 11.5px;
  font-weight: 600;
  margin-bottom: 4px;
}

.tpf-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  padding: 14px 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.85);

  .tpf-error {
    flex: 1 1 auto;
    color: #dc2626;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
    margin-right: auto;
  }

  .tpf-footer-actions {
    display: flex;
    gap: 8px;
    margin-left: auto;
  }
}

// Shared secondary/primary buttons -- used in both the footer and the
// inline app mini-form, so they live at the top level rather than nested
// under .tpf-footer.
.tpf-btn-secondary,
.tpf-btn-primary {
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
}

.tpf-btn-secondary {
  background: #ffffff;
  border-color: rgba(203, 213, 225, 0.9);
  color: #475569;

  &:hover {
    background: #f8fafc;
  }
}

.tpf-btn-primary {
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

Note this moves `.tpf-btn-secondary`/`.tpf-btn-primary` out from under `.tpf-footer` to the top level, since the new app mini-form's Cancel/Save buttons reuse the same two classes outside the footer's DOM subtree.

- [ ] **Step 4: Rewrite the component spec**

Replace the full contents of `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.spec.ts` with:

```typescript
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AppReference, SmartSuggestion } from '../../core/data/smart-tasks.data';
import { TaskPresetFormComponent } from './task-preset-form.component';

describe('TaskPresetFormComponent', () => {
  let fixture: ComponentFixture<TaskPresetFormComponent>;
  let component: TaskPresetFormComponent;
  let http: HttpTestingController;

  const rawApp = (overrides: Record<string, unknown> = {}) => ({
    pkg: 'com.android.chrome',
    name: 'Chrome',
    icon: 'public',
    category: 'browser',
    is_builtin: true,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TaskPresetFormComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(TaskPresetFormComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    // AppRegistryService (injected for the app picker) eagerly loads its list.
    http.expectOne('/api/apps').flush([rawApp()]);
  });

  afterEach(() => http.verify());

  it('starts empty in create mode', () => {
    component.ngOnChanges({} as never);

    expect(component.title()).toBe('');
    expect(component.isValid).toBeFalse();
  });

  it('pre-fills fields when editing an existing task', () => {
    const task: SmartSuggestion = {
      id: 'task-1',
      title: 'Find Coffee',
      description: 'desc',
      goal: 'goal',
      profile: 'flash',
      category: 'flash',
      tag: 'Maps',
      apps: [{ name: 'Maps', icon: 'explore', pkg: 'com.google.android.apps.maps' }],
      requiredPackages: ['com.google.android.apps.maps']
    };
    component.editingTask = task;

    component.ngOnChanges({ editingTask: {} as never });

    expect(component.title()).toBe('Find Coffee');
    expect(component.isPkgSelected('com.google.android.apps.maps')).toBeTrue();
  });

  it('requires at least one selected app to be valid', () => {
    component.ngOnChanges({} as never);
    component.title.set('T');
    component.description.set('D');
    component.goal.set('G');

    expect(component.isValid).toBeFalse();

    component.togglePkg('com.android.chrome');

    expect(component.isValid).toBeTrue();
  });

  it('emits save with the derived payload', () => {
    component.ngOnChanges({} as never);
    component.title.set('T');
    component.description.set('D');
    component.goal.set('G');
    component.togglePkg('com.android.chrome');

    let emitted: unknown = null;
    component.save.subscribe(v => (emitted = v));
    component.onSave();

    expect(emitted).toEqual({
      title: 'T',
      description: 'D',
      goal: 'G',
      profile: 'flash',
      app_pkgs: ['com.android.chrome']
    });
  });

  it('emits cancel', () => {
    let called = false;
    component.cancel.subscribe(() => (called = true));
    component.onCancel();
    expect(called).toBeTrue();
  });

  it('opens the add-app form empty and requires a pkg to be valid', () => {
    component.openAddAppForm();

    expect(component.showAppForm()).toBeTrue();
    expect(component.editingApp()).toBeNull();
    expect(component.appFormPkg()).toBe('');
    expect(component.isAppFormValid).toBeFalse();

    component.appFormPkg.set('com.example.newapp');
    component.appFormName.set('New App');

    expect(component.isAppFormValid).toBeTrue();
  });

  it('opens the edit-app form pre-filled and does not require re-entering pkg', () => {
    const app: AppReference = { name: 'Chrome', icon: 'public', pkg: 'com.android.chrome', category: 'browser' };

    component.openEditAppForm(app, new Event('click'));

    expect(component.editingApp()).toEqual(app);
    expect(component.appFormName()).toBe('Chrome');
    expect(component.isAppFormValid).toBeTrue();
  });

  it('creates a new app via the mini-form and closes it on success', () => {
    component.openAddAppForm();
    component.appFormPkg.set('com.example.newapp');
    component.appFormName.set('New App');
    component.appFormIcon.set('star');

    component.saveApp();

    const req = http.expectOne('/api/apps');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ pkg: 'com.example.newapp', name: 'New App', icon: 'star', category: 'general' });
    req.flush(rawApp({ pkg: 'com.example.newapp', name: 'New App', icon: 'star', category: 'general' }));

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([rawApp(), rawApp({ pkg: 'com.example.newapp', name: 'New App' })]);

    expect(component.showAppForm()).toBeFalse();
  });

  it('shows an inline error when saving an app fails', () => {
    component.openAddAppForm();
    component.appFormPkg.set('com.android.chrome');
    component.appFormName.set('Chrome Again');

    component.saveApp();

    const req = http.expectOne('/api/apps');
    req.flush({ detail: "App 'com.android.chrome' already exists." }, { status: 409, statusText: 'Conflict' });

    expect(component.appFormError()).toBe("App 'com.android.chrome' already exists.");
    expect(component.showAppForm()).toBeTrue();
  });

  it('deletes an app and shows an inline error when blocked by a referencing preset', () => {
    const app: AppReference = { name: 'Chrome', icon: 'public', pkg: 'com.android.chrome', category: 'browser' };

    component.deleteApp(app, new Event('click'));

    const req = http.expectOne('/api/apps/com.android.chrome');
    expect(req.request.method).toBe('DELETE');
    req.flush({ detail: 'Used by 2 task preset(s).' }, { status: 409, statusText: 'Conflict' });

    expect(component.appDeleteError()).toBe('Used by 2 task preset(s).');
  });
});
```

- [ ] **Step 5: Verify**

If `ng test` works in your environment: `cd apps/showcase_ui && npx ng test --watch=false --include='**/task-preset-form.component.spec.ts'`, expect PASS (11 tests).

If not: `cd apps/showcase_ui && npx ng build` — expect a fully clean build now (this was the last file blocking it after Task 4). Then manually trace each of the 11 spec assertions against the component code, the same rigor as the prior plan's Task 5. Write the trace into your report.

- [ ] **Step 6: Commit**

```bash
git add apps/showcase_ui/src/app/components/task-preset-form
git commit -m "feat: add inline app add/edit/delete to the task form's app picker"
```

---

### Task 6: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend admin_console test suite**

Run: `uv run pytest tests/unit/admin_console -v`
Expected: All PASS except the two pre-existing, unrelated `test_model_service.py` failures if your environment reproduces those (see the prior plan's ledger for why they're pre-existing and out of scope).

- [ ] **Step 2: Run the full backend test suite**

Run: `uv run pytest tests/unit -v`
Expected: No new failures beyond whatever pre-existing baseline your environment already has (compare failing test names against a run from before this plan's first commit if you're unsure — do not assume a failing test is caused by this plan without checking).

- [ ] **Step 3: Frontend verification**

If `ng test` works in your environment: `cd apps/showcase_ui && npx ng test --watch=false`, expect all PASS.

If not: `cd apps/showcase_ui && npx ng build`, expect a clean build with no errors, and note in your final report that `ng test` and a real browser pass (create/edit/delete an app from the picker; confirm the 409-blocked-delete message renders; confirm the hover edit/delete icons on chips don't visually collide with the existing selected-state styling) are still needed before this is merged, exactly as flagged for the prior plan.

- [ ] **Step 4: Manual cross-check (only if a real backend + browser are available)**

Start the backend, open the app in a browser, open "Add Task", click "+ Add App", add a new app, confirm it appears as a selectable chip immediately (no reload needed), edit it, then try to delete `Chrome` after building a task preset that uses it — confirm the 409 message appears instead of a silent failure or crash.
