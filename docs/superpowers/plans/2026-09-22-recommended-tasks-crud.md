# Recommended Tasks CRUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create, edit, and delete "Recommended Tasks" cards from the showcase UI home page, with the backend (SQLite) as the single source of truth, replacing the two independent hardcoded lists that exist today (frontend `smart-tasks.data.ts` and backend `task_preset_catalog.py`).

**Architecture:** A new `task_presets` SQLite table (bootstrapped lazily via a `CREATE TABLE IF NOT EXISTS`, following the existing admin_console repository pattern) is seeded once from the current 13 built-in presets. `TaskRecommendationEngine` reads/writes through a new `TaskPresetRepository` instead of a static Python list. Three new REST endpoints (`POST`/`PUT`/`DELETE /api/tasks/presets`) are added to the existing `tasks.py` router. The Angular `TaskRecommendationService` switches from a static array to `HttpClient` calls against `/api/tasks/catalog` and the new endpoints; the home page gains an "Add Task" card and per-card edit/delete controls that open a new `TaskPresetFormComponent` modal.

**Tech Stack:** FastAPI + Pydantic + sqlite3 (backend, `apps/admin_console`), Angular 17+ standalone components + signals + `HttpClient` (frontend, `apps/showcase_ui`), pytest (`pytest-asyncio` for router tests), Angular/Karma (`ng test`).

**Spec:** `docs/superpowers/specs/2026-09-22-recommended-tasks-crud-design.md`

## Global Constraints

- Backend is the single source of truth; the frontend's static `SMART_TASK_LIBRARY` is deleted.
- All 13 built-in presets become ordinary, fully editable/deletable rows (`is_builtin` is a display hint only, never a permission gate).
- `APP_REGISTRY` (app icon/name/package metadata for the picker) stays a static frontend file in `smart-tasks.data.ts` — do not move it server-side.
- Create/edit form fields are exactly: title, description, goal prompt, profile (flash/pro), and one-or-more apps picked from `APP_REGISTRY`. The server derives `tag`, `apps`, `required_packages`, `category`, `match_mode` (`"any"`), and `priority` (`60` for user-created tasks) — none of these are user-facing fields.
- Delete requires a simple confirmation (`confirm()` is sufficient; no custom dialog component).
- No auth/ownership model — any UI user may edit/delete any task (local single-user tool).

---

### Task 1: `TaskPresetRepository` (backend persistence)

**Files:**
- Create: `apps/admin_console/database/repositories/task_preset_repository.py`
- Test: `tests/unit/admin_console/test_task_preset_repository.py`

**Interfaces:**
- Consumes: `apps.admin_console.database.connection.db_session(db_path)` (existing context manager, returns a `sqlite3.Connection` with `row_factory = sqlite3.Row`).
- Produces: `TaskPresetRepository` with methods `list_all() -> list[dict]`, `create(row: dict) -> dict`, `update(preset_id: str, fields: dict) -> dict | None`, `delete(preset_id: str) -> bool`, `seed_if_empty(rows: list[dict]) -> None`; and the module-level singleton `task_preset_repository = TaskPresetRepository()`. Row dicts always have keys: `id, title, description, goal, profile, category, tag, apps, required_packages, match_mode, priority, is_builtin, created_at, updated_at`, with `apps`/`required_packages` as native Python lists (not JSON strings) and `is_builtin` as a Python `bool`. Task 2 consumes this.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_task_preset_repository.py`:

```python
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
            {"name": "Test App", "icon": "star", "pkg": "com.test.app", "category": "tools"}
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
        {"name": "Test App", "icon": "star", "pkg": "com.test.app", "category": "tools"}
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.admin_console.database.repositories.task_preset_repository'`

- [ ] **Step 3: Implement `TaskPresetRepository`**

Create `apps/admin_console/database/repositories/task_preset_repository.py`:

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

import json
import sqlite3
from typing import Any

try:
    from admin_console.database.connection import db_session
except ImportError:
    from apps.admin_console.database.connection import db_session


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_presets (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    goal TEXT NOT NULL,
    profile TEXT NOT NULL,
    category TEXT NOT NULL,
    tag TEXT NOT NULL,
    apps TEXT NOT NULL,
    required_packages TEXT NOT NULL,
    match_mode TEXT NOT NULL DEFAULT 'any',
    priority INTEGER NOT NULL DEFAULT 60,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_COLUMNS = [
    "id",
    "title",
    "description",
    "goal",
    "profile",
    "category",
    "tag",
    "apps",
    "required_packages",
    "match_mode",
    "priority",
    "is_builtin",
    "created_at",
    "updated_at",
]


class TaskPresetRepository:
    """Repository for user-editable Recommended Task presets."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_TABLE_SQL)

    @staticmethod
    def _encode_value(column: str, value: Any) -> Any:
        if column in ("apps", "required_packages"):
            return json.dumps(value)
        if column == "is_builtin":
            return 1 if value else 0
        return value

    @classmethod
    def _encode_values(cls, row: dict[str, Any], columns: list[str]) -> list[Any]:
        return [cls._encode_value(c, row[c]) for c in columns]

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["apps"] = json.loads(d["apps"])
        d["required_packages"] = json.loads(d["required_packages"])
        d["is_builtin"] = bool(d["is_builtin"])
        return d

    def list_all(self) -> list[dict[str, Any]]:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            cursor = conn.execute("SELECT * FROM task_presets ORDER BY priority DESC")
            return [self._decode_row(row) for row in cursor.fetchall()]

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            conn.execute(
                f"INSERT INTO task_presets ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                self._encode_values(row, _COLUMNS),
            )
            conn.commit()
        return {**row}

    def update(self, preset_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        settable = [c for c in _COLUMNS if c in fields and c not in ("id", "is_builtin", "created_at")]
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            if settable:
                assignments = ", ".join(f"{c} = ?" for c in settable)
                values = self._encode_values(fields, settable)
                values.append(preset_id)
                cursor = conn.execute(
                    f"UPDATE task_presets SET {assignments} WHERE id = ?", values
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return None
            row = conn.execute(
                "SELECT * FROM task_presets WHERE id = ?", (preset_id,)
            ).fetchone()
        return self._decode_row(row) if row else None

    def delete(self, preset_id: str) -> bool:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            cursor = conn.execute("DELETE FROM task_presets WHERE id = ?", (preset_id,))
            conn.commit()
            return cursor.rowcount > 0

    def seed_if_empty(self, rows: list[dict[str, Any]]) -> None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            existing = conn.execute("SELECT COUNT(*) AS n FROM task_presets").fetchone()["n"]
            if existing > 0:
                return
            for row in rows:
                conn.execute(
                    f"INSERT OR IGNORE INTO task_presets ({', '.join(_COLUMNS)}) "
                    f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                    self._encode_values(row, _COLUMNS),
                )
            conn.commit()


task_preset_repository = TaskPresetRepository()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_repository.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/admin_console/database/repositories/task_preset_repository.py tests/unit/admin_console/test_task_preset_repository.py
git commit -m "feat: add TaskPresetRepository for Recommended Tasks persistence"
```

---

### Task 2: `TaskRecommendationEngine` becomes repository-backed

**Files:**
- Modify: `apps/admin_console/services/task_preset_catalog.py`
- Test: `tests/unit/admin_console/test_task_preset_catalog.py`

**Interfaces:**
- Consumes: `TaskPresetRepository` from Task 1 (`list_all`, `create`, `update`, `delete`, `seed_if_empty`), and the existing module-level `APP_REGISTRY: dict[str, dict[str, str]]` and `PRESET_TASK_CATALOG: list[TaskPreset]` already defined in this file.
- Produces: `TaskRecommendationEngine(repository: TaskPresetRepository | None = None)` with:
  - `get_all_tasks() -> list[dict]`
  - `get_app_registry() -> dict[str, dict[str, str]]` (new — fixes a pre-existing bug: `/api/tasks/catalog` already calls `task_recommendation_engine.get_app_registry()` but the method never existed)
  - `recommend_tasks(installed_packages, category="all", limit=12) -> list[dict]` (same contract/behavior as before, now DB-backed)
  - `create_task(payload: dict) -> dict` — `payload` has `title, description, goal, profile, app_pkgs`; raises `ValueError` for an unknown package or empty `app_pkgs`.
  - `update_task(preset_id: str, payload: dict) -> dict | None` — same payload shape as `create_task`; returns `None` if `preset_id` doesn't exist; raises `ValueError` on invalid `app_pkgs`.
  - `delete_task(preset_id: str) -> bool`
  - module-level singleton `task_recommendation_engine = TaskRecommendationEngine()` (unchanged name — Task 3 consumes this).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_task_preset_catalog.py`:

```python
import pytest

from apps.admin_console.database.repositories.task_preset_repository import (
    TaskPresetRepository,
)
from apps.admin_console.services.task_preset_catalog import TaskRecommendationEngine


def _engine(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    return TaskRecommendationEngine(repository=repo)


def test_get_all_tasks_seeds_the_13_builtin_presets(tmp_path):
    engine = _engine(tmp_path)

    tasks = engine.get_all_tasks()

    assert len(tasks) == 13
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_catalog.py -v`
Expected: FAIL — `TypeError: TaskRecommendationEngine.__init__() got an unexpected keyword argument 'repository'` (and `get_app_registry`/`create_task`/`update_task`/`delete_task` don't exist yet)

- [ ] **Step 3: Rewrite `TaskRecommendationEngine`**

In `apps/admin_console/services/task_preset_catalog.py`, add these imports directly below the existing `from pydantic import BaseModel, Field` line:

```python
from datetime import datetime, timezone
import uuid

try:
    from admin_console.database.repositories.task_preset_repository import (
        TaskPresetRepository,
        task_preset_repository,
    )
except ImportError:
    from apps.admin_console.database.repositories.task_preset_repository import (
        TaskPresetRepository,
        task_preset_repository,
    )
```

Then replace the entire block starting at `class TaskRecommendationEngine:` through the final `task_recommendation_engine = TaskRecommendationEngine()` line (the whole "RECOMMENDATION ENGINE" section at the end of the file) with:

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


class TaskRecommendationEngine:
    """Intelligent recommendation engine matching device capabilities."""

    def __init__(self, repository: TaskPresetRepository | None = None):
        self.repository = repository or task_preset_repository
        self._seeded = False

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        self.repository.seed_if_empty(_builtin_seed_rows())
        self._seeded = True

    def get_all_tasks(self) -> list[dict[str, Any]]:
        self._ensure_seeded()
        return self.repository.list_all()

    def get_app_registry(self) -> dict[str, dict[str, str]]:
        return APP_REGISTRY

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
        apps = []
        for pkg in app_pkgs:
            info = APP_REGISTRY.get(pkg)
            if not info:
                raise ValueError(f"Unknown app package: {pkg}")
            apps.append(
                AppInfo(name=info["name"], icon=info["icon"], pkg=pkg, category=info.get("category", "general"))
            )
        return apps

    def _derive_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        app_pkgs = payload["app_pkgs"]
        if not app_pkgs:
            raise ValueError("At least one app must be selected.")
        apps = self._resolve_apps(app_pkgs)
        profile = payload["profile"]
        category = "cross_app" if len(app_pkgs) > 1 else profile
        tag = " + ".join(a.name for a in apps)
        return {
            "title": payload["title"],
            "description": payload["description"],
            "goal": payload["goal"],
            "profile": profile,
            "category": category,
            "tag": tag,
            "apps": [a.model_dump() for a in apps],
            "required_packages": app_pkgs,
            "match_mode": "any",
            "priority": 60,
        }

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
        fields = self._derive_fields(payload)
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self.repository.update(preset_id, fields)

    def delete_task(self, preset_id: str) -> bool:
        self._ensure_seeded()
        return self.repository.delete(preset_id)


task_recommendation_engine = TaskRecommendationEngine()
```

Leave `AppInfo`, `TaskPreset`, `APP_REGISTRY`, and `PRESET_TASK_CATALOG` (the 13-entry list) exactly as they are — they're still used as the seed source and for app-package validation.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_catalog.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run Task 1's tests too, to confirm no regression**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_repository.py tests/unit/admin_console/test_task_preset_catalog.py -v`
Expected: PASS (14 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/admin_console/services/task_preset_catalog.py tests/unit/admin_console/test_task_preset_catalog.py
git commit -m "feat: back TaskRecommendationEngine with TaskPresetRepository"
```

---

### Task 3: CRUD API endpoints

**Files:**
- Modify: `apps/admin_console/schemas/task_schema.py`
- Modify: `apps/admin_console/routers/tasks.py:1-67` (imports + the area right after `get_task_catalog`)
- Test: `tests/unit/admin_console/test_task_preset_endpoints.py`

**Interfaces:**
- Consumes: `task_recommendation_engine.create_task/update_task/delete_task` from Task 2 (raises `ValueError` on bad input, returns `None` from `update_task` for a missing id).
- Produces: `POST /api/tasks/presets`, `PUT /api/tasks/presets/{preset_id}`, `DELETE /api/tasks/presets/{preset_id}` route handlers `create_task_preset`, `update_task_preset`, `delete_task_preset` in `apps/admin_console/routers/tasks.py`, importable by tests as `apps.admin_console.routers.tasks.create_task_preset` etc.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/admin_console/test_task_preset_endpoints.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_endpoints.py -v`
Expected: FAIL — `ImportError: cannot import name 'TaskPresetWrite' from 'apps.admin_console.schemas.task_schema'`

- [ ] **Step 3: Add the `TaskPresetWrite` schema**

In `apps/admin_console/schemas/task_schema.py`, change the top import line from:

```python
from pydantic import BaseModel
```

to:

```python
from typing import Literal

from pydantic import BaseModel, Field
```

Then append this class at the end of the file (after `StopRequest`):

```python
class TaskPresetWrite(BaseModel):
    title: str
    description: str
    goal: str
    profile: Literal["flash", "pro"]
    app_pkgs: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add the three endpoints to the router**

In `apps/admin_console/routers/tasks.py`, update both `try`/`except ImportError` import blocks (currently lines 28-40) to also import `TaskPresetWrite`:

```python
try:
    from admin_console.core.state import state
    from admin_console.database.repositories.session_repository import session_repo
    from admin_console.schemas.task_schema import RunRequest, TaskPresetWrite
    from admin_console.services.ipc_service import ipc_service
    from admin_console.services.model_service import model_service
    from admin_console.services.task_preset_catalog import task_recommendation_engine
    from admin_console.services.task_queue_service import task_queue_service
except ImportError:
    from apps.admin_console.core.state import state
    from apps.admin_console.database.repositories.session_repository import session_repo
    from apps.admin_console.schemas.task_schema import RunRequest, TaskPresetWrite
    from apps.admin_console.services.ipc_service import ipc_service
    from apps.admin_console.services.model_service import model_service
    from apps.admin_console.services.task_preset_catalog import task_recommendation_engine
    from apps.admin_console.services.task_queue_service import task_queue_service
```

Then insert these three route handlers right after `get_task_catalog` (i.e. between the end of that function and the `@router.post("/api/run")` line):

```python
@router.post("/api/tasks/presets")
async def create_task_preset(request: TaskPresetWrite):
    """Create a new user-defined Recommended Task preset."""
    try:
        return task_recommendation_engine.create_task(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/api/tasks/presets/{preset_id}")
async def update_task_preset(preset_id: str, request: TaskPresetWrite):
    """Replace the editable fields of an existing Recommended Task preset."""
    try:
        updated = task_recommendation_engine.update_task(preset_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task preset '{preset_id}' not found.")
    return updated


@router.delete("/api/tasks/presets/{preset_id}")
async def delete_task_preset(preset_id: str):
    """Delete a Recommended Task preset (built-in or user-created)."""
    deleted = task_recommendation_engine.delete_task(preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task preset '{preset_id}' not found.")
    return {"status": "deleted", "id": preset_id}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_task_preset_endpoints.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Run the full admin_console test directory to confirm no regression**

Run: `uv run pytest tests/unit/admin_console -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add apps/admin_console/schemas/task_schema.py apps/admin_console/routers/tasks.py tests/unit/admin_console/test_task_preset_endpoints.py
git commit -m "feat: add create/update/delete API endpoints for task presets"
```

---

### Task 4: Frontend `TaskRecommendationService` becomes HTTP-backed

**Files:**
- Modify: `apps/showcase_ui/src/app/core/data/smart-tasks.data.ts:16-334`
- Modify: `apps/showcase_ui/src/app/core/services/task-recommendation.service.ts` (full rewrite)
- Test: `apps/showcase_ui/src/app/core/services/task-recommendation.service.spec.ts`

**Interfaces:**
- Consumes: backend endpoints from Task 3 — `GET /api/tasks/catalog` (returns `{tasks: RawTaskPreset[], app_registry: ...}`), `POST /api/tasks/presets`, `PUT /api/tasks/presets/{id}`, `DELETE /api/tasks/presets/{id}`.
- Produces: `TaskRecommendationService` with `allTasks: Signal<SmartSuggestion[]>`, `appRegistry: Record<string, AppReference>` (unchanged, still local), `loadTasks(): Observable<...>`, `createTask(payload: TaskPresetWritePayload): Observable<SmartSuggestion>`, `updateTask(id: string, payload: TaskPresetWritePayload): Observable<SmartSuggestion>`, `deleteTask(id: string): Observable<{status: string; id: string}>`, and unchanged `isSuggestionOnDevice`/`filterAndRankTasks` (now reading `this.allTasks()` instead of `this.allTasks`). Exported type `TaskPresetWritePayload = {title: string; description: string; goal: string; profile: 'flash' | 'pro'; app_pkgs: string[]}`. Task 5 and Task 6 consume this.

- [ ] **Step 1: Trim `smart-tasks.data.ts`**

In `apps/showcase_ui/src/app/core/data/smart-tasks.data.ts`:

1. Add an `isBuiltin?: boolean;` field to the `SmartSuggestion` interface:

```typescript
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
```

2. Delete the `/** Curated, clean task preset library ... */` comment and the entire `export const SMART_TASK_LIBRARY: SmartSuggestion[] = [ ... ];` block that follows it (currently lines 77-334, ending at the file's closing `];`). Nothing else in the file changes — `AppReference`, `SuggestionCategory`, `SmartSuggestion`, and `APP_REGISTRY` all stay.

- [ ] **Step 2: Write the failing service spec**

Create `apps/showcase_ui/src/app/core/services/task-recommendation.service.spec.ts`:

```typescript
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { TaskRecommendationService } from './task-recommendation.service';

describe('TaskRecommendationService', () => {
  let service: TaskRecommendationService;
  let http: HttpTestingController;

  const rawTask = (overrides: Record<string, unknown> = {}) => ({
    id: 'task-1',
    title: 'Find Coffee',
    description: 'desc',
    goal: 'goal',
    profile: 'flash',
    category: 'flash',
    tag: 'Maps',
    apps: [
      { name: 'Maps', icon: 'explore', pkg: 'com.google.android.apps.maps', category: 'navigation' }
    ],
    required_packages: ['com.google.android.apps.maps'],
    match_mode: 'any',
    priority: 95,
    is_builtin: true,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        TaskRecommendationService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(TaskRecommendationService);
    http = TestBed.inject(HttpTestingController);
    // The constructor eagerly loads the catalog; drain that request first.
    http.expectOne('/api/tasks/catalog').flush({ tasks: [] });
  });

  afterEach(() => http.verify());

  it('maps snake_case API fields to camelCase SmartSuggestion fields', () => {
    service.loadTasks().subscribe();
    const req = http.expectOne('/api/tasks/catalog');
    req.flush({ tasks: [rawTask()] });

    const loaded = service.allTasks();
    expect(loaded.length).toBe(1);
    expect(loaded[0].requiredPackages).toEqual(['com.google.android.apps.maps']);
    expect(loaded[0].matchMode).toBe('any');
    expect(loaded[0].isBuiltin).toBe(true);
  });

  it('creates a task then refreshes the list', () => {
    service.createTask({
      title: 'New',
      description: 'd',
      goal: 'g',
      profile: 'flash',
      app_pkgs: ['com.android.chrome']
    }).subscribe();

    const createReq = http.expectOne('/api/tasks/presets');
    expect(createReq.request.method).toBe('POST');
    createReq.flush(rawTask({ id: 'task-2' }));

    const refreshReq = http.expectOne('/api/tasks/catalog');
    refreshReq.flush({ tasks: [rawTask({ id: 'task-2' })] });

    expect(service.allTasks().map(t => t.id)).toEqual(['task-2']);
  });

  it('updates a task by id then refreshes the list', () => {
    service.updateTask('task-1', {
      title: 'Renamed',
      description: 'd',
      goal: 'g',
      profile: 'flash',
      app_pkgs: ['com.android.chrome']
    }).subscribe();

    const updateReq = http.expectOne('/api/tasks/presets/task-1');
    expect(updateReq.request.method).toBe('PUT');
    updateReq.flush(rawTask({ title: 'Renamed' }));

    const refreshReq = http.expectOne('/api/tasks/catalog');
    refreshReq.flush({ tasks: [rawTask({ title: 'Renamed' })] });

    expect(service.allTasks()[0].title).toBe('Renamed');
  });

  it('deletes a task by id then refreshes the list', () => {
    service.deleteTask('task-1').subscribe();

    const deleteReq = http.expectOne('/api/tasks/presets/task-1');
    expect(deleteReq.request.method).toBe('DELETE');
    deleteReq.flush({ status: 'deleted', id: 'task-1' });

    const refreshReq = http.expectOne('/api/tasks/catalog');
    refreshReq.flush({ tasks: [] });

    expect(service.allTasks()).toEqual([]);
  });
});
```

- [ ] **Step 3: Run the spec to verify it fails**

Run: `cd apps/showcase_ui && npx ng test --watch=false --include='**/task-recommendation.service.spec.ts'`
Expected: FAIL — compile error, `allTasks` is a plain array/`loadTasks`/`createTask`/`updateTask`/`deleteTask` don't exist yet.

- [ ] **Step 4: Rewrite `TaskRecommendationService`**

Replace the full contents of `apps/showcase_ui/src/app/core/services/task-recommendation.service.ts` with:

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
import {
  AppReference,
  SmartSuggestion,
  SuggestionCategory,
  APP_REGISTRY
} from '../data/smart-tasks.data';

export interface TaskPresetWritePayload {
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  app_pkgs: string[];
}

interface RawTaskPreset {
  id: string;
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  category: 'flash' | 'pro' | 'cross_app' | 'monitor';
  tag: string;
  apps: AppReference[];
  required_packages: string[];
  match_mode: 'any' | 'all';
  priority: number;
  is_builtin: boolean;
}

function mapPreset(raw: RawTaskPreset): SmartSuggestion {
  return {
    id: raw.id,
    title: raw.title,
    description: raw.description,
    goal: raw.goal,
    profile: raw.profile,
    category: raw.category,
    tag: raw.tag,
    apps: raw.apps,
    requiredPackages: raw.required_packages,
    matchMode: raw.match_mode,
    priority: raw.priority,
    isBuiltin: raw.is_builtin
  };
}

@Injectable({
  providedIn: 'root'
})
export class TaskRecommendationService {
  private http = inject(HttpClient);

  public readonly appRegistry = APP_REGISTRY;
  public allTasks = signal<SmartSuggestion[]>([]);

  constructor() {
    this.loadTasks().subscribe();
  }

  /**
   * Fetches the full task preset catalog from the backend and replaces
   * `allTasks`. Called on service init and after every mutation.
   */
  public loadTasks(): Observable<{ tasks: RawTaskPreset[] }> {
    return this.http.get<{ tasks: RawTaskPreset[] }>('/api/tasks/catalog').pipe(
      tap({
        next: (response) => this.allTasks.set(response.tasks.map(mapPreset)),
        error: (err) => console.error('Failed to load task presets:', err)
      })
    );
  }

  public createTask(payload: TaskPresetWritePayload): Observable<SmartSuggestion> {
    return this.http.post<RawTaskPreset>('/api/tasks/presets', payload).pipe(
      tap(() => this.loadTasks().subscribe()),
      map((raw) => mapPreset(raw))
    );
  }

  public updateTask(id: string, payload: TaskPresetWritePayload): Observable<SmartSuggestion> {
    return this.http.put<RawTaskPreset>(`/api/tasks/presets/${id}`, payload).pipe(
      tap(() => this.loadTasks().subscribe()),
      map((raw) => mapPreset(raw))
    );
  }

  public deleteTask(id: string): Observable<{ status: string; id: string }> {
    return this.http.delete<{ status: string; id: string }>(`/api/tasks/presets/${id}`).pipe(
      tap({
        next: () => this.loadTasks().subscribe()
      })
    );
  }

  /**
   * Check if task matches any package installed on device
   */
  public isSuggestionOnDevice(
    suggestion: SmartSuggestion,
    installedPackages: Set<string>
  ): boolean {
    if (installedPackages.size === 0) return false;
    if (!suggestion.requiredPackages || suggestion.requiredPackages.length === 0) {
      return true;
    }

    if (suggestion.matchMode === 'all') {
      return suggestion.requiredPackages.every(pkg => installedPackages.has(pkg));
    }
    return suggestion.requiredPackages.some(pkg => installedPackages.has(pkg));
  }

  /**
   * Intelligently rank and filter tasks:
   * Prioritizes tasks matching apps detected on user's phone without exposing clutter.
   */
  public filterAndRankTasks(
    installedPackages: Set<string>,
    category: SuggestionCategory,
    shuffleOffset: number = 0
  ): SmartSuggestion[] {
    const hasDevice = installedPackages.size > 0;

    // 1. Score tasks: prioritize tasks whose apps are on the user's phone
    const scored = this.allTasks().map(task => {
      const isMatched = this.isSuggestionOnDevice(task, installedPackages);
      let score = task.priority ?? 50;

      if (hasDevice) {
        if (isMatched) {
          score += 100;
          if (task.requiredPackages && task.requiredPackages.length > 1 && task.matchMode === 'all') {
            score += 30; // bonus for full multi-app synergy match
          }
        } else {
          score -= 40;
        }
      }

      return { task, isMatched, score };
    });

    // 2. Filter by category
    let filtered = scored.filter(item => {
      if (category === 'flash') {
        return item.task.profile === 'flash';
      }
      if (category === 'pro') {
        return item.task.profile === 'pro';
      }
      if (category === 'cross_app') {
        return item.task.category === 'cross_app';
      }
      if (category === 'monitor') {
        return item.task.category === 'monitor';
      }
      return true; // 'all'
    });

    // 3. Sort by score descending (matched apps first)
    filtered.sort((a, b) => b.score - a.score);

    let result = filtered.map(f => f.task);

    // 4. Apply shuffle rotation
    if (shuffleOffset > 0 && result.length > 0) {
      const shift = shuffleOffset % result.length;
      result = [...result.slice(shift), ...result.slice(0, shift)];
    }

    return result;
  }
}
```

- [ ] **Step 5: Run the spec to verify it passes**

Run: `cd apps/showcase_ui && npx ng test --watch=false --include='**/task-recommendation.service.spec.ts'`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/showcase_ui/src/app/core/data/smart-tasks.data.ts apps/showcase_ui/src/app/core/services/task-recommendation.service.ts apps/showcase_ui/src/app/core/services/task-recommendation.service.spec.ts
git commit -m "feat: back TaskRecommendationService with the task presets API"
```

**Note:** after this task, `apps/showcase_ui/src/app/pages/home/home.component.ts` will fail to compile (it references `taskRecService.allTasks` as a plain array at line 492 and imports `SmartSuggestion`/`SuggestionCategory` re-exported from this service's old shape). This is expected and fixed in Task 6 — do not attempt to fix `home.component.ts` in this task.

---

### Task 5: `TaskPresetFormComponent` (create/edit modal)

**Files:**
- Create: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.ts`
- Create: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.html`
- Create: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.scss`
- Test: `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.spec.ts`

**Interfaces:**
- Consumes: `TaskRecommendationService.appRegistry` (Task 4, for the app picker), `SmartSuggestion` type (Task 4's `smart-tasks.data.ts`), `TaskPresetWritePayload` type (Task 4's service).
- Produces: `TaskPresetFormComponent` (selector `app-task-preset-form`) with `@Input() editingTask: SmartSuggestion | null`, `@Output() save: EventEmitter<TaskPresetWritePayload>`, `@Output() cancel: EventEmitter<void>`. Task 6 consumes this as `<app-task-preset-form [editingTask]="..." (save)="..." (cancel)="...">`.

- [ ] **Step 1: Write the failing spec**

Create `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.spec.ts`:

```typescript
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SmartSuggestion } from '../../core/data/smart-tasks.data';
import { TaskPresetFormComponent } from './task-preset-form.component';

describe('TaskPresetFormComponent', () => {
  let fixture: ComponentFixture<TaskPresetFormComponent>;
  let component: TaskPresetFormComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TaskPresetFormComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(TaskPresetFormComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    // TaskRecommendationService (injected for appRegistry) eagerly loads its catalog.
    http.expectOne('/api/tasks/catalog').flush({ tasks: [] });
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
});
```

- [ ] **Step 2: Run the spec to verify it fails**

Run: `cd apps/showcase_ui && npx ng test --watch=false --include='**/task-preset-form.component.spec.ts'`
Expected: FAIL — `Cannot find module './task-preset-form.component'`

- [ ] **Step 3: Implement the component TypeScript**

Create `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.ts`:

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
import { AppReference, SmartSuggestion } from '../../core/data/smart-tasks.data';
import { TaskPresetWritePayload, TaskRecommendationService } from '../../core/services/task-recommendation.service';

@Component({
  selector: 'app-task-preset-form',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './task-preset-form.component.html',
  styleUrl: './task-preset-form.component.scss'
})
export class TaskPresetFormComponent implements OnChanges {
  @Input() editingTask: SmartSuggestion | null = null;
  @Output() save = new EventEmitter<TaskPresetWritePayload>();
  @Output() cancel = new EventEmitter<void>();

  private taskRecService = inject(TaskRecommendationService);
  public appRegistryEntries: Array<[string, AppReference]> = Object.entries(this.taskRecService.appRegistry);

  public title = signal<string>('');
  public description = signal<string>('');
  public goal = signal<string>('');
  public profile = signal<'flash' | 'pro'>('flash');
  public selectedPkgs = signal<Set<string>>(new Set());

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
}
```

- [ ] **Step 4: Implement the component template**

Create `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.html`:

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
        <div class="tpf-app-chips">
          @for (entry of appRegistryEntries; track entry[0]) {
            <button
              type="button"
              class="tpf-app-chip"
              [class.selected]="isPkgSelected(entry[0])"
              (click)="togglePkg(entry[0])"
            >
              <span class="material-symbols-outlined">{{ entry[1].icon }}</span>
              <span>{{ entry[1].name }}</span>
            </button>
          }
        </div>
      </div>
    </div>

    <div class="tpf-footer">
      <button type="button" class="tpf-btn-secondary" (click)="onCancel()">Cancel</button>
      <button type="button" class="tpf-btn-primary" [disabled]="!isValid" (click)="onSave()">Save</button>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Implement the component styles**

Create `apps/showcase_ui/src/app/components/task-preset-form/task-preset-form.component.scss`:

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
  textarea {
    border: 1px solid rgba(203, 213, 225, 0.9);
    border-radius: 10px;
    padding: 8px 10px;
    font-size: 13px;
    font-family: inherit;
    color: #0f172a;
    resize: vertical;

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
  gap: 6px;
  max-height: 160px;
  overflow-y: auto;
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

.tpf-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.85);

  button {
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
}
```

- [ ] **Step 6: Run the spec to verify it passes**

Run: `cd apps/showcase_ui && npx ng test --watch=false --include='**/task-preset-form.component.spec.ts'`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add apps/showcase_ui/src/app/components/task-preset-form
git commit -m "feat: add TaskPresetFormComponent for create/edit modal"
```

---

### Task 6: Wire the home page — Add Task card, edit/delete controls, modal

**Files:**
- Modify: `apps/showcase_ui/src/app/pages/home/home.component.ts`
- Modify: `apps/showcase_ui/src/app/pages/home/home.component.html:1978-2092`
- Modify: `apps/showcase_ui/src/app/pages/home/home.component.scss` (append near the `.suggestions-cards-grid` block, currently around line 4819)

**Interfaces:**
- Consumes: `TaskPresetFormComponent` (Task 5), `TaskRecommendationService.createTask/updateTask/deleteTask` (Task 4), existing `errorMessage: WritableSignal<string | null>` (already defined in `home.component.ts`, reused here for CRUD failures — no new error UI is introduced).
- Produces: no new consumers — this is the last task.

**Note:** `home.component.ts`/`home.component.html` are page-level components with no existing unit test coverage in this codebase (only services and utils have `.spec.ts` files here) — this task does not add one, to match that convention. Verify this task by running the dev server and exercising the feature by hand (Step 6 below), plus a full `ng build` to catch compile errors.

- [ ] **Step 1: Update `home.component.ts` imports and remove the now-invalid `allSuggestions` field**

Add `TaskPresetFormComponent` and `TaskPresetWritePayload` to the import block near the top of `apps/showcase_ui/src/app/pages/home/home.component.ts` — change:

```typescript
import { TaskRecommendationService } from '../../core/services/task-recommendation.service';
```

to:

```typescript
import { TaskPresetWritePayload, TaskRecommendationService } from '../../core/services/task-recommendation.service';
import { TaskPresetFormComponent } from '../../components/task-preset-form/task-preset-form.component';
```

Add `TaskPresetFormComponent` to the component's `imports` array:

```typescript
@Component({
  selector: 'app-home',
  standalone: true,
  imports: [FormsModule, TaskPresetFormComponent],
  templateUrl: './home.component.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './home.component.scss'
})
```

Delete the now-dead line (Task 4 made `taskRecService.allTasks` a `Signal`, and this field was never referenced elsewhere):

```typescript
  // Rich Smart Suggestions Library (Device-Aware, Flash vs Pro Tailored)
  public readonly allSuggestions = this.taskRecService.allTasks;
```

- [ ] **Step 2: Add modal state and CRUD handler methods**

Immediately after the existing `filteredSuggestions` computed signal (right after its closing `});`), add:

```typescript
  // Recommended Tasks CRUD modal state
  public showTaskModal = signal<boolean>(false);
  public editingTask = signal<SmartSuggestion | null>(null);

  public openAddTaskModal(): void {
    this.editingTask.set(null);
    this.showTaskModal.set(true);
  }

  public openEditTaskModal(item: SmartSuggestion, event: Event): void {
    event.stopPropagation();
    this.editingTask.set(item);
    this.showTaskModal.set(true);
  }

  public closeTaskModal(): void {
    this.showTaskModal.set(false);
    this.editingTask.set(null);
  }

  public saveTaskPreset(payload: TaskPresetWritePayload): void {
    const editing = this.editingTask();
    const request$ = editing
      ? this.taskRecService.updateTask(editing.id, payload)
      : this.taskRecService.createTask(payload);
    request$.subscribe({
      next: () => this.closeTaskModal(),
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to save task preset.');
      }
    });
  }

  public deleteTaskPreset(item: SmartSuggestion, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Delete "${item.title}"?`)) {
      return;
    }
    this.taskRecService.deleteTask(item.id).subscribe({
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to delete task preset.');
      }
    });
  }
```

- [ ] **Step 3: Update the Recommended Tasks grid markup**

In `apps/showcase_ui/src/app/pages/home/home.component.html`, replace the `<!-- Suggestions Grid -->` block (currently lines 2049-2092: the `<div class="suggestions-cards-grid">...</div>` and its closing `</div>` for `.smart-suggestions-container`) with:

```html
          <!-- Suggestions Grid -->
          <div class="suggestions-cards-grid">
            <button type="button" class="add-task-card" (click)="openAddTaskModal()">
              <span class="material-symbols-outlined add-task-icon">add</span>
              <span>Add Task</span>
            </button>

            @for (item of filteredSuggestions(); track item.id) {
              <div
                class="suggestion-card"
                [class.is-pro-card]="item.profile === 'pro'"
                [class.is-flash-card]="item.profile === 'flash'"
                (click)="applySuggestion(item)"
              >
                <div class="card-hover-actions">
                  <button type="button" class="card-action-btn" title="Edit" (click)="openEditTaskModal(item, $event)">
                    <span class="material-symbols-outlined">edit</span>
                  </button>
                  <button type="button" class="card-action-btn card-action-danger" title="Delete" (click)="deleteTaskPreset(item, $event)">
                    <span class="material-symbols-outlined">delete</span>
                  </button>
                </div>

                <!-- Top Row: App Icon + Name + Mode Badge -->
                <div class="card-top-row">
                  <div class="app-icons-cluster">
                    @for (app of item.apps; track app.name) {
                      <div class="app-icon-badge" [title]="app.name">
                        <span class="material-symbols-outlined">{{ app.icon }}</span>
                      </div>
                    }
                    <span class="app-names-label">{{ getAppNamesDisplay(item.apps) }}</span>
                  </div>

                  <div class="badges-wrap">
                    @if (item.isBuiltin) {
                      <span class="builtin-badge" title="Built-in preset">Built-in</span>
                    }
                    <span class="mode-badge" [class.mode-pro]="item.profile === 'pro'" [class.mode-flash]="item.profile === 'flash'"
                      [title]="item.profile === 'pro' ? 'Uses ARTEMIS Pro (Multi-Agent Cognitive State Graph)' : 'Uses ARTEMIS Flash (Reactive Fast Loop)'">
                      {{ item.profile === 'pro' ? 'Pro' : 'Flash' }}
                    </span>
                  </div>
                </div>

                <!-- Middle Content: Title + Description -->
                <div class="card-body">
                  <h4 class="card-title">{{ item.title }}</h4>
                  <p class="card-desc">{{ item.description }}</p>
                </div>

                <!-- Bottom Footer Row: Tag & Action -->
                <div class="card-footer-row">
                  <span class="tag-pill">{{ item.tag }}</span>
                  <div class="use-prompt-action">
                    <span>Use</span>
                    <span class="material-symbols-outlined action-arrow">arrow_forward</span>
                  </div>
                </div>
              </div>
            }
          </div>
        </div>

        @if (showTaskModal()) {
          <app-task-preset-form
            [editingTask]="editingTask()"
            (save)="saveTaskPreset($event)"
            (cancel)="closeTaskModal()"
          ></app-task-preset-form>
        }

```

(This keeps the pre-existing closing `</div>` for `.smart-suggestions-container` right after the grid, and adds the modal outside it, before the section's own closing tags.)

- [ ] **Step 4: Add CSS for the new card controls**

In `apps/showcase_ui/src/app/pages/home/home.component.scss`, inside the `.suggestion-card { ... }` rule, add a sibling to `.card-top-row` (e.g. right after the `.card-top-row { ... }` block closes, before `.card-body { ... }`):

```scss
            .card-hover-actions {
              position: absolute;
              top: 10px;
              right: 10px;
              display: flex;
              gap: 4px;
              opacity: 0;
              transition: opacity 0.15s ease;
              z-index: 2;

              .card-action-btn {
                width: 24px;
                height: 24px;
                border-radius: 7px;
                border: 1px solid rgba(226, 232, 240, 0.9);
                background: rgba(255, 255, 255, 0.92);
                color: #475569;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;

                span {
                  font-size: 14px;
                }

                &:hover {
                  background: #ffffff;
                  border-color: rgba(191, 219, 254, 0.95);
                  color: #1a73e8;
                }

                &.card-action-danger:hover {
                  border-color: rgba(254, 202, 202, 0.95);
                  color: #ef4444;
                }
              }
            }
```

And, still inside `.suggestion-card { ... }`, next to the existing `&:hover .use-prompt-action { ... }` rule, add:

```scss
            &:hover .card-hover-actions {
              opacity: 1;
            }
```

Inside the `.card-top-row { ... }` rule, add a `.badges-wrap` rule alongside the existing `.app-icons-cluster` and `.mode-badge` rules:

```scss
              .badges-wrap {
                display: flex;
                align-items: center;
                gap: 6px;
                flex-shrink: 0;

                .builtin-badge {
                  padding: 2px 7px;
                  border-radius: 8px;
                  font-size: 10px;
                  font-weight: 700;
                  line-height: 1.2;
                  background: rgba(100, 116, 139, 0.12);
                  color: #64748b;
                  border: 1px solid rgba(100, 116, 139, 0.2);
                }
              }
```

Finally, inside `.suggestions-cards-grid { ... }` (as a sibling of `.suggestion-card { ... }`), add:

```scss
          .add-task-card {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 6px;
            min-height: 128px;
            border-radius: 16px;
            border: 1.5px dashed rgba(148, 163, 184, 0.55);
            background: rgba(248, 250, 252, 0.6);
            color: #64748b;
            font-size: 12.5px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;

            .add-task-icon {
              font-size: 22px;
            }

            &:hover {
              border-color: rgba(26, 115, 232, 0.55);
              color: #1a73e8;
              background: rgba(255, 255, 255, 0.9);
            }
          }
```

- [ ] **Step 5: Build to confirm the frontend compiles**

Run: `cd apps/showcase_ui && npx ng build`
Expected: Build succeeds with no TypeScript or template errors.

- [ ] **Step 6: Manual smoke test**

Run the backend and frontend dev servers (see `artemis-cli` skill / project README for exact commands, e.g. `uv run artemis ui` or the showcase_ui `npm start` against a running admin_console backend), open the home page, and verify:
1. The Recommended Tasks grid loads the 13 built-in presets from the backend (not instant/synchronous — confirm via Network tab that `/api/tasks/catalog` is called).
2. Clicking "Add Task" opens the modal; filling in title/description/goal, picking an app, and saving adds a new card to the grid.
3. Hovering an existing card shows edit/delete icons; editing pre-fills the modal and saving updates the card in place.
4. Deleting a card (including a built-in one) prompts a confirm dialog and removes it from the grid after confirming.
5. Reloading the page shows the same set of tasks (persisted in SQLite), confirming the backend is the source of truth.

- [ ] **Step 7: Run the full frontend test suite to confirm no regression**

Run: `cd apps/showcase_ui && npx ng test --watch=false`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/showcase_ui/src/app/pages/home/home.component.ts apps/showcase_ui/src/app/pages/home/home.component.html apps/showcase_ui/src/app/pages/home/home.component.scss
git commit -m "feat: add create/edit/delete controls to the Recommended Tasks grid"
```

---

### Task 7: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend admin_console test suite**

Run: `uv run pytest tests/unit/admin_console -v`
Expected: All PASS.

- [ ] **Step 2: Run the full backend test suite**

Run: `uv run pytest tests/unit -v`
Expected: All PASS (no unrelated regressions from the `task_preset_catalog.py` rewrite).

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd apps/showcase_ui && npx ng test --watch=false`
Expected: All PASS.

- [ ] **Step 4: Run the frontend production build**

Run: `cd apps/showcase_ui && npx ng build`
Expected: Succeeds.
