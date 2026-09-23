# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ARTEMIS is an LLM-driven agent that operates real Android devices (via ADB) from natural-language goals. It is exposed through four surfaces that all share the same core in `artemis/`: a Typer CLI (`artemis`), an MCP server (`mcp_server/`), a FastAPI admin console + Angular web UI (`apps/`), and Python SDKs (`artemis/interfaces/sdk`, plus the zero-dependency remote client in `packages/artemis-client`).

## Commands

Python is managed with `uv` (Python ≥3.12). The frontend lives in `apps/showcase_ui` (Angular, Node 22).

```bash
make install          # uv sync --dev
make test             # deterministic suite (no device, no credentials) — what CI runs
make lint             # ruff format --check + ruff check + quality ratchet
make format           # ruff format + ruff check --fix
make typecheck        # pyright on the protected core modules in pyright-core.json
make test-integration # may need model credentials
make test-device      # needs an attached, authorized Android device/emulator

uv run pytest tests/unit/test_cli.py::test_name   # single test
uv run pytest tests/unit/admin_console -k schedule

cd apps/showcase_ui && npm test -- --watch=false --browsers=ChromeHeadless   # frontend tests
cd apps/showcase_ui && npm run build                                          # frontend build (served by the admin console)

uv run artemis run "<goal>" --profile flash   # run a task on the connected device
uv run artemis ui --open                      # start admin console + web UI (http://localhost:8000)
uv run artemis doctor                         # environment/device diagnostics
```

### Test markers and layout

`pyproject.toml` `addopts` deselects `integration`, `e2e`, `cloud`, `manual`, and `android` markers by default, and `--strict-markers` is on. Any test needing external state must carry the right marker and still be collectable without that dependency. Default `testpaths` are `tests/unit`, `tests/tools` (per-agent/tool tests using fixtures in `tests/tools/inputs` and a mocked ADB client), and `packages/artemis-client/tests`. `pythonpath` includes `apps` and `apps/admin_console`, which is why admin-console modules import as `admin_console.*` with a fallback to `apps.admin_console.*`.

### Lint constraints

- Relative imports are banned (ruff `TID` with `ban-relative-imports = "all"`); always use absolute imports. Line length 100.
- `scripts/quality_ratchet.py` fails if the counts of broad `except Exception`/bare-except handlers or `# type: ignore` comments in `artemis/`, `mcp_server/`, `apps/admin_console/` exceed `.quality-baseline.json`. Silent broad handlers (`except Exception: pass`) must stay at 0. Catch specific exceptions; lower the baseline when you remove debt.
- Pyright is only enforced on the files listed in `pyright-core.json`.

## Architecture

### Two execution profiles

Every task runs as either **Flash** or **Pro**; the dispatch point is `artemis/sdk/agent.py`.

- **Flash** (`artemis/agents/flash/runner.py`, `FlashRunner`): a single-model reactive observe→think→act loop with no graph. Tools are bound as Google GenAI function declarations; actions go through `artemis/mcp/action_executor.py`. History is compressed (`context_compressor.py`, `summarizer.py`) rather than capped.
- **Pro** (`artemis/graph/graph.py`, `get_graph`): a LangGraph `StateGraph` of agent nodes — `planner` → `convergence` → `perception` → `operator` → `execution_check` → (`validator` → `summarizer`) → back to `convergence`, ending via `exit_settlement`. The Planner keeps a Markdown `task_plan` note (milestones, `[Loop]` tags, `verify:`/`assert:` check lines); plan writes are intercepted and validated in `graph.py`. The Checker verifies checkpoints/final review; the Explorer does visual grounding at a user-configured tier (flash/pro/ultra). State is in `artemis/graph/state.py`.

Both profiles share the session transcript/memory layer in `artemis/memory/` (step capsules, chunked history recallable via `search_history`/`replay_steps`) and the trace/data store in `artemis/data_engine/`.

### Agents, prompts, and tools

- Each agent lives in `artemis/agents/<name>/`. Prompts are data, not code: `<name>.json` holds named `blocks` (Jinja2 templates) and `modes` that list which blocks form the system prompt and the human template. Flash prompts are `.md` files next to the runner. `artemis/agents/prompt_assembly.py` renders tool enumerations from the *actually available* tool set so absent tools never appear in prompts — keep tool mentions in prompts going through it.
- Tools are authored once against the protocol in `artemis/tools/base.py` (Pydantic schema + async handler) and exported to LangChain tools (Pro), GenAI function declarations (Flash), and MCP tools. Action specs shared by Flash and MCP live in `artemis/mcp/action_specs.py` / `action_manifest.py`.
- `artemis/context.py` (`ArtemisContext`) is the per-task object threaded through nodes and tools (device, config, data engine, etc.).

### Device layer

`artemis/drivers/` (`android/adb_driver.py`, `cloud/`, `mock/`, chosen by `drivers/factory.py`) sits beneath `artemis/controllers/` and `artemis/clients/`. The UI hierarchy comes from the on-device **Accessibility Helper** APK (`packages/artemis-accessibility-helper`, managed by `artemis/runtime/helper_manager.py`) with UIAutomator2 fallback (`ARTEMIS_HIERARCHY_BACKEND`). `artemis/runtime/` handles device locking/queue tickets (`device_lock.py`), device pools, keep-awake, cancel markers, and server lifecycle.

### Process model

Long-running tasks run in **separate worker subprocesses**, not in the server process:
- Admin console (`apps/admin_console/services/task_queue_service.py`) spawns `python -m artemis.main <goal> --profile ... --session-id ...`, and stops workers gracefully via cancel markers before hard-killing.
- MCP server (`mcp_server/tools/task_runner.py`) spawns `python -m mcp_server.background.task_runner`.
- Both reserve a device via `DeviceExecutionLock` and pass the queue ticket through env.

`artemis/main.py` is a compat entrypoint that inserts `run` when the first arg isn't a known subcommand; the real CLI is `artemis/interfaces/cli/main.py` with commands in `interfaces/cli/commands/`.

### Admin console + web UI

`apps/admin_console/server.py` is a FastAPI app with routers in `routers/` (tasks, sessions, steps, replay, stream, media, schedules, system), services in `services/` (task queue, APScheduler-based task scheduler, device screen streaming, IPC), and SQLAlchemy repositories in `database/`. The Angular app (`apps/showcase_ui/src/app`, pages: home, workspace, schedules) talks to it; `proxy.conf.json` proxies the dev server. The built UI is bundled into the wheel (`artemis/resources`).

### Configuration

- `config/artemis.jsonc` — model/provider per agent node (`default`, `presets`, `nodes.<agent>`), profile settings (e.g. `pro.explorer.mode`, `flash.explorer_mode`, `agent.flash.max_turns`). Resolved by `artemis/config/paths.py` in order: env var override → `config/` → repo root → user config dir → app dir → wheel-bundled default. Pydantic config models are in `artemis/config/`.
- `.env` (see `.env.example`) — provider API keys, ADB host/port, `ARTEMIS_DEFAULT_PROFILE`, helper and hierarchy-backend toggles.

### MCP rules

`mcp_server/rules.md` is the behavioral rules file installed into users' IDEs by `artemis mcp --install <client>`; treat it as user-facing product content, not internal docs. Usage of the CLI itself is documented in the `artemis-cli` project skill (`.claude/skills/artemis-cli`).
