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

    def get(self, preset_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            row = conn.execute(
                "SELECT * FROM task_presets WHERE id = ?", (preset_id,)
            ).fetchone()
        return self._decode_row(row) if row else None

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
