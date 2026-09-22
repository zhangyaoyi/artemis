# Recommended Tasks CRUD — Design

Date: 2026-09-22
Status: Approved for planning

## Problem

The showcase UI's home page shows a "Recommended Tasks" grid, sourced entirely
from a hardcoded array (`apps/showcase_ui/src/app/core/data/smart-tasks.data.ts`,
`SMART_TASK_LIBRARY`). A near-identical hardcoded catalog also exists on the
backend (`apps/admin_console/services/task_preset_catalog.py`,
`PRESET_TASK_CATALOG`) and is exposed via `GET /api/tasks/presets` and
`GET /api/tasks/catalog`, but the frontend never calls either endpoint — it
reads only its own local copy. Users cannot add, edit, or remove entries from
either list without editing source code.

Goal: let users create, edit, and delete Recommended Tasks from the UI, with
the backend as the single source of truth, replacing both hardcoded lists.

## Scope decisions (confirmed)

- **Who can edit:** anyone using the UI. Artemis is a local single-user tool;
  no auth/ownership model is introduced.
- **Source of truth:** the backend. The existing frontend static list is
  deleted; the UI reads/writes through the backend API.
- **The 13 built-in presets:** migrated into the database as ordinary rows
  (seed data) with `is_builtin=1`. `is_builtin` is a display hint only (e.g. a
  small "built-in" tag) — it does **not** block editing or deletion. Once
  seeded, built-ins are indistinguishable from user-created tasks for CRUD
  purposes.
- **`APP_REGISTRY`** (app name/icon/package metadata used to build the app
  picker) stays a static frontend file, unchanged. It is UI metadata, not user
  data, and is small enough that duplicating it is not worth the complexity of
  moving it server-side.
- **Form complexity:** simplified. Users fill in title, description, goal
  prompt, profile (flash/pro), and pick one or more apps from `APP_REGISTRY`.
  The server derives `tag`, `apps` (name/icon/category), `required_packages`,
  `category`, `match_mode`, and `priority` — none of these are user-facing
  fields.
- **Delete confirmation:** a simple confirm step (native `confirm()` is
  sufficient — consistent with a local single-user tool with no existing
  custom dialog component for this).

## Architecture

```
Home component (Angular)
   │  create / update / delete / list
   ▼
TaskRecommendationService (HTTP client)
   │  REST
   ▼
/api/tasks/presets*  (FastAPI router: apps/admin_console/routers/tasks.py)
   │
   ▼
TaskPresetRepository (apps/admin_console/database/repositories/task_preset_repository.py)
   │  SQLite (existing DB_PATH, same connection helper as other repositories)
   ▼
task_presets table
```

`TaskRecommendationEngine` (scoring/ranking logic in `task_preset_catalog.py`)
is unchanged in behavior; it stops reading a static Python list and instead
loads current rows from `TaskPresetRepository` on each call.

## Data model

New SQLite table `task_presets`, initialized via the existing schema
bootstrap path (same mechanism `StorageManager` uses for other tables):

| column             | type    | notes                                          |
|--------------------|---------|-------------------------------------------------|
| id                 | TEXT PK | existing preset ids for seeds; `uuid4` for new  |
| title              | TEXT    |                                                   |
| description        | TEXT    |                                                   |
| goal               | TEXT    |                                                   |
| profile            | TEXT    | `flash` \| `pro`                                 |
| category           | TEXT    | `flash` \| `pro` \| `cross_app` \| `monitor`     |
| tag                | TEXT    | derived display label (e.g. "Maps + Messages")   |
| apps               | TEXT    | JSON array of `{name, icon, pkg, category}`      |
| required_packages  | TEXT    | JSON array of package ids                        |
| match_mode         | TEXT    | `any` \| `all`, default `any`                    |
| priority           | INTEGER | default 60 for user-created tasks                |
| is_builtin         | INTEGER | 0/1, display hint only                           |
| created_at         | TEXT    | ISO timestamp                                    |
| updated_at         | TEXT    | ISO timestamp                                    |

**Seeding:** on first access, if `task_presets` is empty, insert the 13
entries currently in `PRESET_TASK_CATALOG` with `is_builtin=1`, `created_at` =
`updated_at` = seed time. This runs once; subsequent starts see a non-empty
table and skip seeding.

## API

All under the existing `tasks.py` router.

- `GET /api/tasks/presets?category=&packages=&limit=` — unchanged contract,
  now DB-backed (recommendation/ranking endpoint).
- `GET /api/tasks/catalog` — unchanged contract, now DB-backed (full list +
  app registry passthrough for backward compatibility, though the frontend's
  own `APP_REGISTRY` is what the picker actually uses).
- `POST /api/tasks/presets` — create. Body: `{title, description, goal,
  profile, app_pkgs: string[]}`. Server resolves `app_pkgs` against the
  backend's own app registry (`task_preset_catalog.APP_REGISTRY`) to build
  `apps`; unknown packages are rejected with 422. Derives `tag`,
  `required_packages`, `category` (`cross_app` if `len(app_pkgs) > 1` else
  `profile`), `match_mode="any"`, `priority=60`. Returns the created row.
- `PUT /api/tasks/presets/{id}` — update. Same body shape as create, full
  replace of the editable fields. 404 if id not found.
- `DELETE /api/tasks/presets/{id}` — delete. 404 if id not found. 200 with no
  body on success.

Pydantic request/response models added to `apps/admin_console/schemas/`
alongside the existing `task_schema.py`.

## Frontend changes

- Delete `SMART_TASK_LIBRARY` from `smart-tasks.data.ts`; keep
  `AppReference`, `SmartSuggestion`, `SuggestionCategory` types and
  `APP_REGISTRY`.
- `TaskRecommendationService`:
  - `allTasks` becomes a signal/observable populated by `loadTasks()` (calls
    `GET /api/tasks/catalog`), fetched once on service init and re-fetched
    after any mutating call.
  - Add `createTask()`, `updateTask()`, `deleteTask()` wrapping the new
    endpoints; each resolves then triggers a `loadTasks()` refresh (no
    optimistic updates — simplest correct behavior, acceptable at this
    scale/latency).
  - `filterAndRankTasks()` client-side logic is unchanged.
- Home component (`suggestions-cards-grid`):
  - Add an "＋ Add Task" card, opens a modal with the simplified form (title,
    description, goal, profile toggle, multi-select app chips sourced from
    `APP_REGISTRY`).
  - Each existing suggestion card gets edit/delete icon buttons (visible on
    hover, matching existing card hover affordances). Edit opens the same
    modal pre-filled. A small "built-in" badge shows when `is_builtin` is
    true, purely informational.
  - Delete triggers `confirm('Delete this task?')` before calling
    `deleteTask()`.
  - On any CRUD failure, show the error inline (reuse the app's existing
    error/toast pattern) and leave the current list as-is.

## Error handling

- Create/update: 422 on invalid payload (missing required field, unknown app
  package) via Pydantic validation — surfaced verbatim in the modal.
- Update/delete: 404 if the id no longer exists (e.g. deleted in another tab)
  — surfaced as a toast and triggers a list refresh so the UI self-corrects.
- Network/server errors: generic inline error, list state untouched.

## Testing

**Backend**
- `TaskPresetRepository`: create/list/update/delete, and empty-table seeding
  behavior (unit tests against a temp SQLite file).
- `TaskRecommendationEngine`: scoring/ranking still correct when sourced from
  the repository instead of the static list.
- API tests for `POST`/`PUT`/`DELETE /api/tasks/presets`: happy path, 404 on
  missing id, 422 on invalid app package.

**Frontend**
- `TaskRecommendationService`: `loadTasks()` populates `allTasks` from the
  mocked HTTP response; create/update/delete call the right endpoints and
  trigger a refresh.
- Home component: add/edit modal submits expected payload; delete calls
  `confirm()` and only deletes on confirmation; existing filter/rank tests
  updated to use the now-dynamic `allTasks` source instead of importing the
  deleted static constant.

## Out of scope

- Per-user ownership/auth for presets (single local user, as decided above).
- Soft-delete/undo for deleted presets.
- Moving `APP_REGISTRY` server-side.
- Changing the existing recommendation scoring algorithm.
