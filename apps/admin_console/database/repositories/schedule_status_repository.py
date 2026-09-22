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

"""SQLite-backed store for a Task Scheduler schedule's last-run outcome.

This is deliberately the only custom persistence the Task Scheduler feature
owns. A schedule's trigger definition (cron expression / run-at time, next
run time, paused state) lives entirely inside APScheduler's own
`apscheduler_jobs` table -- see `task_scheduler_service.py`.
"""

import sqlite3
from typing import Any

try:
    from admin_console.database.connection import db_session
except ImportError:
    from apps.admin_console.database.connection import db_session


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schedule_run_status (
    job_id TEXT PRIMARY KEY,
    last_run_at TEXT NOT NULL,
    last_status TEXT NOT NULL
)
"""


class ScheduleStatusRepository:
    """Repository for the last-run outcome of a Task Scheduler job."""

    def __init__(self, db_path=None):
        self.db_path = db_path

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_TABLE_SQL)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            row = conn.execute(
                "SELECT * FROM schedule_run_status WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def set(self, job_id: str, last_run_at: str, last_status: str) -> None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            conn.execute(
                """
                INSERT INTO schedule_run_status (job_id, last_run_at, last_status)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    last_run_at = excluded.last_run_at,
                    last_status = excluded.last_status
                """,
                (job_id, last_run_at, last_status),
            )
            conn.commit()

    def delete(self, job_id: str) -> None:
        with db_session(self.db_path) as conn:
            self._ensure_table(conn)
            conn.execute("DELETE FROM schedule_run_status WHERE job_id = ?", (job_id,))
            conn.commit()


schedule_status_repository = ScheduleStatusRepository()
