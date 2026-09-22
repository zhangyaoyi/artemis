# Task Scheduler — Design

Date: 2026-09-23
Status: Approved for planning

## Problem

Recommended Task presets (see `2026-09-22-recommended-tasks-crud-design.md`)
can only be run manually, by clicking "Run" in the UI. There is no way to
have a preset run automatically — once at a future time, or on a recurring
cadence (e.g. "clear cache every weekday morning"). This adds a Task
Scheduler: CRUD over schedules that reference an existing preset, each
firing either once at a specific time or repeatedly on a cron expression,
with the actual trigger/timing delegated to APScheduler rather than
hand-rolled.

## Scope decisions (confirmed)

- **What a schedule runs:** an existing Recommended Task preset
  (`task_presets.id`), not a free-form goal. A preset may have any number
  of independent schedules pointing at it.
- **Schedule types:** `once` (a specific datetime, fires exactly one time)
  and `cron` (a raw cron expression, e.g. `0 9 * * 1,3,5`). No day-of-week
  checkboxes / simplified recurrence UI — cron covers that need directly.
- **Conflict handling at fire time:** the scheduled run is submitted through
  the exact same path as a manual "Run" click
  (`task_queue_service.enqueue_tasks`), so it queues behind whatever the
  device is already doing, with no special-casing.
- **No full run-history log.** Only the most recent run's timestamp and
  outcome are kept per schedule.
- **No per-schedule device targeting.** Mirrors current manual-run
  behavior — device resolution is untouched.
- **Persistence is delegated to APScheduler**, not a hand-rolled table +
  poll loop. APScheduler's `SQLAlchemyJobStore` is the system of record for
  trigger definitions, next-run time, and pause/resume state. The only
  custom persistence is a one-column-pair side table for last-run outcome,
  which the job store has no field for.

## Architecture

```
SchedulesPageComponent (new page, new nav tab)
   │  create / edit / delete / pause / resume
   ▼
ScheduleService (new, HTTP client)
   │  REST
   ▼
/api/schedules*  (new router: schedules.py)
   │
   ▼
TaskSchedulerService (new, apps/admin_console/services/task_scheduler_service.py)
   │  wraps AsyncIOScheduler
   ▼
APScheduler (SQLAlchemyJobStore, same sqlite file as DB_PATH)
   │  at fire time, calls the top-level job function
   ▼
run_scheduled_task(preset_id, schedule_id)
   │  re-reads preset fresh, then:
   ▼
task_queue_service.enqueue_tasks(...)   (same call the manual "Run" button makes)
```

`AsyncIOScheduler` is started and shut down in `server.py`'s lifespan
(`on_startup`/shutdown), next to the existing `state.worker_task =
asyncio.create_task(task_queue_service.queue_worker())` line, following the
same background-task-ownership pattern already used there.

## Persistence

- `AsyncIOScheduler(jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")})`.
  Uses the same sqlite file as the rest of the app (already WAL mode +
  `busy_timeout=10000` per `apps/admin_console/database/connection.py`, so
  it tolerates concurrent access from the app's plain `sqlite3` connections
  fine). APScheduler auto-creates and owns its own `apscheduler_jobs` table
  there — no schema for it is written by this feature.
- New dependencies in `pyproject.toml`: `apscheduler` and `sqlalchemy`
  (SQLAlchemy is currently only a transitive dependency of something else
  in the tree; pin it directly since `SQLAlchemyJobStore` imports it
  directly).
- One small side table, `schedule_run_status`, created the same lazy
  `CREATE TABLE IF NOT EXISTS` way as `task_presets`/`apps`:

  | column      | type    | notes                                  |
  |-------------|---------|------------------------------------------|
  | job_id      | TEXT PK | == APScheduler job id == schedule id     |
  | last_run_at | TEXT    | ISO timestamp, null until first fire     |
  | last_status | TEXT    | `"queued"` \| `"error: <reason>"`        |

  This is the *only* custom persistence in this feature. Deleting a
  schedule also deletes its row here.

## Job function (pickle-safety constraint)

`SQLAlchemyJobStore` pickles a *reference* to the job function, not a
closure — so the callback must be a top-level, importable function with a
stable module path, never a lambda or a bound method capturing local state:

```python
# apps/admin_console/services/task_scheduler_service.py
async def run_scheduled_task(preset_id: str, schedule_id: str) -> None:
    ...
```

At fire time it:
1. Re-reads the preset from `task_preset_repository` fresh (so edits made
   to the preset after the schedule was created are honored, not a stale
   snapshot).
2. If the preset no longer exists: writes
   `last_status="error: preset deleted"` to `schedule_run_status` and calls
   `scheduler.remove_job(schedule_id)` so it stops firing into a void.
3. Otherwise calls `task_queue_service.enqueue_tasks(...)` with the
   preset's `goal`/`profile`/`app_pkgs` (same fields a manual run of that
   preset already uses), then writes `last_run_at`/`last_status="queued"`.
4. `once` schedules: APScheduler already drops a one-shot `DateTrigger` job
   after it fires; nothing further to do.

## CRUD → APScheduler mapping

Schedule id = APScheduler job id, generated by us as `sched_<uuid4 hex>` at
creation time (passed to `add_job` as both `id=` and as an arg, so the
callback knows its own id for status writes).

`CronTrigger` has no `.to_crontab()` method — reconstructing a cron string
from its internal fields is unnecessary work. Instead, the original
user-entered cron string is stored as an extra job kwarg
(`kwargs={"cron_expression": "..."}`) purely so the API can echo it back
verbatim; it is otherwise unused by `run_scheduled_task`.

| Operation | Call |
|---|---|
| Create | Validate first — `CronTrigger.from_crontab(expr)` for `cron` (raises `ValueError` on a bad expression → 422) or construct `DateTrigger(run_date=...)` for `once` (422 if `run_date` is in the past). Then `scheduler.add_job(run_scheduled_task, trigger=trigger, args=[preset_id, schedule_id], kwargs={"cron_expression": expr} if cron, id=schedule_id, misfire_grace_time=300, coalesce=True)`. 404 if `preset_id` doesn't exist. |
| List | `scheduler.get_jobs()` → for each: look up preset title via `task_preset_repository` by `job.args[0]` (soft-fail to `"(preset deleted)"` if missing), read `schedule_run_status` by job id, format `job.next_run_time` (`None` if paused), include the stored `cron_expression` kwarg or `job.trigger.run_date` depending on type. |
| Read (single) | `scheduler.get_job(job_id)`, same enrichment as one list row. 404 if missing. |
| Update | Preset change → `scheduler.modify_job(job_id, args=[new_preset_id, job_id])`. Schedule change (new cron/datetime) → validate, then `scheduler.reschedule_job(job_id, trigger=new_trigger)` (also updates the `cron_expression` kwarg via `modify_job`). 404 if missing. |
| Delete | `scheduler.remove_job(job_id)` + delete the `schedule_run_status` row. 404 if missing. |
| Pause | `scheduler.pause_job(job_id)`. Only meaningful for `cron` jobs — rejected (400) for `once` jobs from the API layer (a paused one-shot job whose fire time has already passed would silently never run again if later resumed past due; simplest to disallow rather than define that behavior). |
| Resume | `scheduler.resume_job(job_id)`. Same `cron`-only restriction. |

## Data model summary

No new schema of our own beyond the tiny `schedule_run_status` table above.
Everything else (trigger type, cron expression / run_at, next run time,
paused state) lives inside APScheduler's own `apscheduler_jobs` table.

## API

New router `apps/admin_console/routers/schedules.py`, registered in
`server.py` alongside the existing routers:

- `GET /api/schedules` — list, enriched as described above.
- `POST /api/schedules` — create. Body: `{preset_id, schedule_type: "once"|"cron", run_at?, cron_expression?}`. 404 unknown preset, 422 invalid cron / past `run_at` / missing the field required by `schedule_type`.
- `PUT /api/schedules/{id}` — update (preset and/or schedule fields). 404 if missing, 422 on invalid new schedule fields.
- `DELETE /api/schedules/{id}` — delete. 404 if missing.
- `POST /api/schedules/{id}/pause` / `POST /api/schedules/{id}/resume` — 404 if missing, 400 if the job is `once`-type.

New Pydantic schemas in `apps/admin_console/schemas/task_schema.py`:
`ScheduleWrite(preset_id: str, schedule_type: Literal["once", "cron"], run_at: str | None = None, cron_expression: str | None = None)`.

## Frontend changes

- New route `/schedules`, new third tab in `nav-switcher.component.ts`
  ("Scheduler" / `schedule` icon) — a dedicated page rather than adding
  another section to the already large `home.component.html`.
- New `SchedulesPageComponent`
  (`apps/showcase_ui/src/app/pages/schedules/`): grid of schedule cards
  (preset title, schedule description — the raw cron string or the `once`
  datetime — next run time, last-run timestamp/status, pause/resume
  toggle, edit/delete icons), "+ New Schedule" button.
- New `ScheduleFormComponent`
  (`apps/showcase_ui/src/app/components/schedule-form/`), modal, following
  `TaskPresetFormComponent`'s structure: preset picker (dropdown over
  existing presets), schedule-type toggle (Once / Cron), and the matching
  input (datetime picker for Once, text field for the cron expression).
  Server-side 422 (invalid cron / past datetime) surfaces inline under the
  relevant field.
- New `ScheduleService`
  (`apps/showcase_ui/src/app/core/services/schedule.service.ts`):
  `schedules: Signal<Schedule[]>`, `loadSchedules()`, `createSchedule()`,
  `updateSchedule()`, `deleteSchedule()`, `pauseSchedule()`,
  `resumeSchedule()` — same eager-load-on-construction pattern as
  `TaskRecommendationService`/`AppRegistryService`.

## Error handling

- Create/Update: 404 unknown `preset_id`, 422 invalid cron expression,
  422 `run_at` in the past.
- Pause/Resume: 400 attempted on a `once` schedule.
- Delete/Read/Pause/Resume on unknown id: 404.
- At fire time, a missing preset is handled inside `run_scheduled_task`
  itself (self-removes the job, records the error) rather than surfacing
  as a request-time error, since nothing is making a request at that
  moment.
- Network/server errors in the UI: generic inline error near the schedule
  list, same convention as the presets/apps pages.

## Testing

**Backend:** `TaskSchedulerService`/router tests against a real
`AsyncIOScheduler` + `SQLAlchemyJobStore` pointed at a temp sqlite file
(not mocked — the whole point is exercising real APScheduler behavior):
create/list/update/delete/pause/resume happy paths, 404s, 422 on bad cron
and past `run_at`, 400 pause-on-`once`. A test that fires a job directly
(short-interval trigger or invoking `run_scheduled_task` directly) and
asserts `schedule_run_status` gets written, including the preset-deleted
self-removal path.

**Frontend:** `ScheduleService` load/create/update/delete/pause/resume
against `HttpTestingController`, mirroring
`task-recommendation.service.spec.ts`. `ScheduleFormComponent` spec for
the Once/Cron toggle and inline validation-error display.
`SchedulesPageComponent` spec for card rendering and the pause/resume
button being hidden for `once` schedules.

## Out of scope

- Free-form (non-preset) scheduled goals.
- Full run-history log (only last run is kept).
- Per-schedule device targeting.
- A cron-expression builder/preview UI (raw text field only).
- Misfire/catch-up policy beyond APScheduler's default
  `misfire_grace_time`/`coalesce` behavior.
