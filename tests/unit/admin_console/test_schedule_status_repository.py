from apps.admin_console.database.repositories.schedule_status_repository import (
    ScheduleStatusRepository,
)


def test_get_returns_none_for_missing_job_id(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    assert repo.get("does-not-exist") is None


def test_set_then_get_round_trips(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.set("sched-1", "2026-09-23T09:00:00", "queued")

    row = repo.get("sched-1")

    assert row["last_run_at"] == "2026-09-23T09:00:00"
    assert row["last_status"] == "queued"


def test_set_overwrites_existing_row(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.set("sched-1", "2026-09-23T09:00:00", "queued")

    repo.set("sched-1", "2026-09-24T09:00:00", "error: preset deleted")

    row = repo.get("sched-1")
    assert row["last_run_at"] == "2026-09-24T09:00:00"
    assert row["last_status"] == "error: preset deleted"


def test_delete_removes_row(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.set("sched-1", "2026-09-23T09:00:00", "queued")

    repo.delete("sched-1")

    assert repo.get("sched-1") is None


def test_delete_missing_job_id_is_a_no_op(tmp_path):
    repo = ScheduleStatusRepository(tmp_path / "status.db")
    repo.delete("does-not-exist")  # must not raise
