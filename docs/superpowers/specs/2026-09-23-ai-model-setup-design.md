# AI Model Setup — Design

Date: 2026-09-23
Status: Approved for planning

## Problem

Onboarding Step 2 ("AI Model Setup") on the admin console home page
(`apps/showcase_ui/src/app/pages/home/home.component.html`) only offers two
hardcoded paths: a bespoke "Google Gemini" card (single API key field) or a
read-only "Custom Configuration" inspector that just displays
`config/artemis.jsonc` / `.env` — there is no way to configure a non-Gemini
provider through the UI at all; you have to hand-edit files.

Underneath, `artemis/llm/router.py`'s `ModelFactory` already dispatches
providers into effectively two protocol families — every provider except
`google`/`vertexai`/`anthropic` routes through `langchain_openai.ChatOpenAI`
(`openai`, `openrouter`, `xai`, `ollama`, `vllm`, `custom` all share that
branch), and `anthropic` uses `langchain_anthropic.ChatAnthropic` natively.
`ModelEndpoint` (the router's internal model) already carries per-instance
`api_key`/`api_base` fields that every branch honors over env vars — but the
config layer that feeds it (`artemis/config/llm.py`'s `LLM` Pydantic model,
and `_resolve_endpoint()` in `artemis/services/llm.py`) has no `api_base`
field and never passes one through, so the capability the router already has
is unreachable from config. The Anthropic branch additionally never passes
`base_url` to `ChatAnthropic` at all, even though `endpoint.api_base` exists.

This spec makes the "Setup" step and its backing config generic across any
OpenAI-protocol-compatible or Anthropic-protocol-compatible endpoint — one
generic base_url + api_key + model_name form per protocol family — instead
of enumerating named providers in the UI.

## Scope decisions (confirmed)

- **Only the global default model** is covered by this change (the `default`
  block in `config/artemis.jsonc`). Per-agent-node overrides (`nodes.<agent>`
  in the jsonc) remain a manual-file-edit "advanced" path; no UI is added to
  edit them.
- **Three setup cards, not two:** Gemini (unchanged, existing dedicated path,
  native Google protocol via `ChatGoogleGenerativeAI`/`ModelProvider.GOOGLE`),
  **OpenAI 兼容** (new, generic), **Anthropic 兼容** (new, generic). Gemini is
  kept as its own card rather than folded into "OpenAI 兼容" because it uses
  a distinct native protocol, not an OpenAI-compatible one.
- **No new `LLMProvider` enum values.** The "protocol family" is a UI/API
  concept only. `protocol="openai"` maps to `provider: "openai"` in the jsonc
  `default` block (or the incoming provider is normalized to `"openai"` on
  save regardless of what named provider it previously was); `protocol="anthropic"`
  maps to `provider: "anthropic"`. Model name is free text, not an enum — it
  depends entirely on what the user's endpoint serves.
- **Read-time classification, no migration script.** If an existing
  `default.provider` in `artemis.jsonc` is one of `openai`/`openrouter`/`xai`/
  `ollama`/`vllm`/`custom`, `GET /model-config-env` classifies it as the
  "OpenAI 兼容" card and echoes back its `model`/`api_base`. `anthropic` maps
  to the "Anthropic 兼容" card. `google`/`vertexai` map to the Gemini card.
- **Secrets stay in `.env`, never in jsonc.** `protocol="openai"` writes its
  key to `OPENAI_API_KEY`; `protocol="anthropic"` writes to
  `ANTHROPIC_API_KEY`. Both are existing env var names — no new ones
  introduced.
- **Not building:** per-node UI editing, new provider enum members, API key
  rotation/multi-profile management, a jsonc migration script.

## Architecture

### 1. Config schema (`artemis/config/llm.py`)

- Add `api_base: str | None = None` to `LLM` (inherited by `LLMWithFallback`).
- `_resolve_endpoint()` in `artemis/services/llm.py` (~line 1067) passes
  `api_base=_get_val(cfg, "api_base", str)` through to the `ModelEndpoint` it
  constructs. (`api_key` is intentionally *not* added to `LLM`/config —
  it continues to come from env/settings inside `ModelFactory.create_model`,
  consistent with every existing provider branch; only `api_base` needs to
  travel through config.)

### 2. Router fix (`artemis/llm/router.py`)

- The `ANTHROPIC` branch (~line 306-331) currently builds `ChatAnthropic`
  without a `base_url`. Add `"base_url": endpoint.api_base` to its kwargs
  dict (filtered out with the rest when `None`), mirroring how the OpenAI
  branch already does `"base_url": base_url`.

### 3. Backend API (`apps/admin_console/routers/system.py`)

- `GET /model-config-env`: no backend change needed. `default_model` in its
  response already echoes the raw `default` block from `artemis.jsonc`
  verbatim (including `api_base`, once Task 2's schema field exists and a
  save has written one) — the frontend derives the `"gemini" | "openai" |
  "anthropic"` card classification from `default_model.provider` directly
  per the rule above, rather than duplicating that logic on the backend.
- New `POST /model-config`, body:
  ```json
  { "protocol": "openai" | "anthropic", "model": "string", "api_base": "string | null", "api_key": "string | null" }
  ```
  - Writes `config/artemis.jsonc`'s `default` block: `provider` (normalized
    per protocol), `model`, `api_base` (omitted/null if empty → provider's
    real default URL applies at request time).
  - Writes `api_key` (if provided) to `.env` under `OPENAI_API_KEY` or
    `ANTHROPIC_API_KEY` per protocol — same file/mechanism the existing
    Gemini save path already uses for `GEMINI_API_KEY`.
  - Runs a lightweight connectivity test after saving (reuses the pattern of
    the current Gemini "test" button: build a `ModelEndpoint` from the saved
    values via `ModelFactory.create_model` and issue a minimal completion),
    returning `{ ok: true }` or `{ ok: false, error: "..." }` without raising
    on failure — the save persists either way, matching current Gemini UX
    where a failed test doesn't roll back the saved key.

### 4. Frontend (`apps/showcase_ui/src/app/pages/home/`)

- `modelSetupMode` signal changes from `'gemini' | 'custom'` to
  `'gemini' | 'openai' | 'anthropic'`.
- Three cards in Step 2, same visual pattern (icon/gradient + description +
  form). Gemini card is unchanged. OpenAI/Anthropic cards share one form
  shape: `Base URL` (optional text input, placeholder shows the protocol's
  real default), `API Key` (existing save/test/clear masked-input pattern),
  `Model` (free-text input, not a dropdown).
- The existing read-only jsonc/`.env` inspector becomes an "Advanced" 折叠区
  (collapsed by default) rather than a third selectable "mode" — it's always
  reachable regardless of which card is active, since it now just reflects
  whatever `default`/`nodes` currently hold.
- `SystemService` gets a `saveModelConfig(protocol, model, api_base, api_key)`
  method calling the new `POST /model-config`; existing
  `fetchModelConfigEnv()` return type gains `protocol`/`api_base`.

## Testing

- **Backend unit tests:**
  - `LLM.api_base` parses/round-trips through `_expand_default_into_nodes` →
    `LLMConfig.model_validate` → `_resolve_endpoint` → `ModelEndpoint.api_base`.
  - Router: `ModelFactory.create_model` for `ANTHROPIC` passes `base_url`
    through to the (mocked) `ChatAnthropic` constructor.
  - `apps/admin_console`: `POST /model-config` success path (writes jsonc +
    .env correctly) and failure path (invalid protocol, connectivity test
    failure surfaced but save still succeeds).
  - `GET /model-config-env` protocol classification for each existing
    provider value (`openai`, `openrouter`, `xai`, `ollama`, `vllm`,
    `custom` → `"openai"`; `anthropic` → `"anthropic"`; `google`,
    `vertexai` → `"gemini"`).
- **Frontend tests** (`home.component.spec.ts`): card switching between the
  three modes, save/test/clear for the new OpenAI/Anthropic forms (mirrors
  existing Gemini test cases), Advanced section still renders when any mode
  is active.
