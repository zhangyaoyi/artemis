# App Registry CRUD — Design

Date: 2026-09-22
Status: Approved for planning

## Problem

The Recommended Tasks CRUD feature (see
`2026-09-22-recommended-tasks-crud-design.md`) lets users create/edit/delete
task presets, but the list of apps a preset can reference —
`APP_REGISTRY` — is still a hardcoded static constant, duplicated in both
`apps/admin_console/services/task_preset_catalog.py` (backend, 22 entries)
and `apps/showcase_ui/src/app/core/data/smart-tasks.data.ts` (frontend,
kept identical by hand). A user who wants to build a task around an app not
in that list has no way to add it without editing source code.

Goal: let users add, edit, and delete apps in the registry from the same
task-creation UI, with the backend as the single source of truth — the same
shape as the task-presets work, applied one layer down.

## Scope decisions (confirmed)

- **Built-in apps (22 entries):** migrated into the database as ordinary
  seed rows with `is_builtin=1`, fully editable/deletable — `is_builtin` is
  a display hint only, identical treatment to task presets.
- **`pkg` (package name, e.g. `com.android.chrome`):** required, free-text,
  user-typed, no validation against real device data. It is the natural
  primary key (already unique in the current registry) and is immutable
  once an app is created — editing an app never changes its `pkg`.
- **Icon selection:** a fixed frontend-only dropdown of Material Symbols
  names, seeded from the ~20 icons already in use across the current
  registry (`explore`, `mail`, `public`, `smart_display`, `settings`,
  `timer`, `calculate`, `photo_library`, `calendar_month`, `note_alt`,
  `storefront`, `chat`, `forum`, `auto_stories`, `restaurant`, `star`,
  `video_library`, `account_balance_wallet`, `headphones`, `music_note`).
  This list is UI-picker metadata, not user data — it stays a static
  frontend constant, same reasoning as keeping `APP_REGISTRY` itself
  frontend-only was rejected but keeping *this narrower* list is fine
  since it never needs to change per-user, only per-release.
- **Deleting a referenced app is blocked.** If any `task_presets` row's
  `required_packages` still contains the `pkg` being deleted, the delete
  is rejected (409) with a count of how many presets reference it, rather
  than silently succeeding or cascading.
- **Entry point:** inline inside `TaskPresetFormComponent`'s existing app
  picker — a "+ Add App" chip plus small edit/delete icons on each existing
  chip. No separate management page.

## Architecture

```
TaskPresetFormComponent (app picker)
   │  add / edit / delete app
   ▼
AppRegistryService (new, HTTP client)
   │  REST
   ▼
/api/apps*  (new router, or added to tasks.py)
   │
   ▼
AppRepository (new, apps/admin_console/database/repositories/app_repository.py)
   │  SQLite (same DB_PATH, same connection helper as task_preset_repository.py)
   ▼
apps table
```

`TaskRecommendationEngine`'s existing app-package validation (used by
`create_task`/`update_task`'s `_resolve_apps`) switches from reading the
static `APP_REGISTRY` dict to querying `AppRepository`, so a newly-added
app becomes a valid task-preset selection immediately, in the same
request/process, with no restart needed.

## Data model

New SQLite table `apps`, same bootstrap mechanism as `task_presets`
(lazy `CREATE TABLE IF NOT EXISTS` in the repository, not
`StorageManager`'s central schema — matching the precedent already
established, and already flagged as a minor, accepted schema-location
deviation in the task-presets work):

| column      | type    | notes                                    |
|-------------|---------|-------------------------------------------|
| pkg         | TEXT PK | e.g. `com.android.chrome`, immutable      |
| name        | TEXT    |                                            |
| icon        | TEXT    | Material Symbols name                     |
| category    | TEXT    | free text, default `"general"`            |
| is_builtin  | INTEGER | 0/1, display hint only                    |
| created_at  | TEXT    | ISO timestamp                             |
| updated_at  | TEXT    | ISO timestamp                             |

**Seeding:** on first access, if `apps` is empty, insert the 22 entries
currently in `APP_REGISTRY` (`task_preset_catalog.py`) with `is_builtin=1`.
Runs once; subsequent starts see a non-empty table and skip seeding. Same
pattern as `task_presets`' `seed_if_empty`.

## API

New endpoints, added to the existing `tasks.py` router (co-located with
the task-preset endpoints since they're both under `/api/`, and this
avoids a near-empty new router file for four small handlers):

- `GET /api/apps` — list all apps.
- `POST /api/apps` — create. Body: `{pkg, name, icon, category}`. 409 if
  `pkg` already exists.
- `PUT /api/apps/{pkg}` — update `name`/`icon`/`category` only (`pkg` is
  the path parameter and is never itself editable). 404 if not found.
- `DELETE /api/apps/{pkg}` — delete. 404 if not found. 409 if any
  `task_presets` row's `required_packages` still contains this `pkg` —
  response body includes the count, e.g.
  `{"detail": "Used by 2 task preset(s)."}`.

`GET /api/tasks/catalog`'s existing `app_registry` key is unchanged in
shape, now sourced from `AppRepository` instead of the static dict.

Pydantic request models (`AppCreate`/`AppUpdate` or a single `AppWrite`)
added to `apps/admin_console/schemas/task_schema.py` alongside the
existing `TaskPresetWrite`.

## Frontend changes

- Delete `APP_REGISTRY` from `smart-tasks.data.ts`; keep the `AppReference`
  type.
- New `AppRegistryService` (`apps/showcase_ui/src/app/core/services/`):
  `apps: Signal<AppReference[]>`, `loadApps()` (called once on init, same
  eager-constructor pattern as `TaskRecommendationService`), `createApp()`,
  `updateApp()`, `deleteApp()`. Kept separate from `TaskRecommendationService`
  for single responsibility — apps and task-presets are different resources
  with different lifecycles.
- New static constant `ICON_OPTIONS: string[]` (the ~20 names listed
  above) in `smart-tasks.data.ts` or a new small file — frontend-only
  picker metadata.
- `TaskPresetFormComponent`: `appRegistryEntries` now sourced from
  `AppRegistryService.apps()` instead of the static import. Each chip
  gains a small edit icon (opens an inline mini-form pre-filled with
  name/icon-dropdown/category, `pkg` shown read-only) and delete icon.
  A trailing "+ Add App" chip opens the same mini-form in create mode
  (all four fields editable, `pkg` required free text). A 409 on delete
  shows "Used by N task(s)" inline near the chip instead of removing it;
  no browser `confirm()` for this case since it's a blocked action, not a
  destructive-with-warning one.

## Error handling

- Create: 409 on duplicate `pkg`, 422 on missing required field.
- Update: 404 on missing `pkg`.
- Delete: 404 on missing `pkg`, 409 when referenced (with count), surfaced
  inline in the picker rather than via `confirm()`.
- Network/server errors: generic inline error near the picker, chip list
  state untouched.

## Testing

**Backend:** `AppRepository` CRUD + seed-once (unit tests against temp
SQLite, mirroring `test_task_preset_repository.py`). `TaskRecommendationEngine`'s
`_resolve_apps` validated against the repository instead of the static
dict. API tests for the four new endpoints: happy path, 404s, 409 on
duplicate create, 409 on referenced delete (seed a task preset that uses
the app first).

**Frontend:** `AppRegistryService` load/create/update/delete against
`HttpTestingController`, mirroring `task-recommendation.service.spec.ts`.
`TaskPresetFormComponent` spec extended to cover the add/edit/delete-app
interactions and the 409-inline-message case.

## Out of scope

- Validating `pkg` against real installed-package data.
- A separate app-management page (entry point is inline in the task form
  only).
- Making the icon list itself user-editable/server-side.
- Cascading delete or any automatic cleanup of task presets referencing a
  deleted app (delete is blocked instead).
- Propagating an app-registry edit (renamed name/icon) into task presets that
  already reference it. A preset's `apps` field is a snapshot taken at
  create/update time, not a live reference — if you rename or re-icon an app
  in the registry, existing presets keep showing the old name/icon until
  that specific preset is itself edited and saved. This is a known
  display-only limitation (the underlying `pkg`/`required_packages` stays
  correct, so task execution is unaffected).
