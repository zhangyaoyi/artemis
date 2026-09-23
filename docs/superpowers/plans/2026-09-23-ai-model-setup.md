# AI Model Setup (OpenAI/Anthropic-compatible) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user configure the global default LLM through two generic protocol-family paths — "OpenAI 兼容" and "Anthropic 兼容" (base URL + API key + model name) — instead of only Gemini or hand-editing `config/artemis.jsonc`.

**Architecture:** Thread a per-instance `api_base` through the existing (already-generic) config → `ModelEndpoint` → `ModelFactory` pipeline, fix the one branch (`ANTHROPIC`) that drops `api_base` on the floor, add one new backend endpoint that safely rewrites only the `default` block of `artemis.jsonc` (preserving comments/`nodes`/`presets`), and reuse the *existing* `/api/system/credentials` and `/api/system/credentials/test` endpoints (which already accept `provider: "openai"|"anthropic"` and an optional `base_url`) for API-key save/test. The Angular Setup card grows from two modes to three (`gemini` | `openai` | `anthropic`) plus an always-available "Advanced" jsonc/`.env` inspector.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, LangChain (`langchain-openai`, `langchain-anthropic`), pytest, pytest-asyncio, httpx `AsyncClient`; Angular 18+ standalone components, signals, Jasmine/Karma.

**Spec:** `docs/superpowers/specs/2026-09-23-ai-model-setup-design.md`

## Global Constraints

- Only the global `default` block in `config/artemis.jsonc` is edited by this feature. `nodes.<agent>` overrides are untouched and remain a manual-edit-only path.
- No new `LLMProvider` enum members. Saved `provider` value is always exactly `"openai"` or `"anthropic"`.
- API keys are never written into `artemis.jsonc`. `protocol="openai"` persists to `.env`'s `OPENAI_API_KEY`; `protocol="anthropic"` to `ANTHROPIC_API_KEY` — both existing variable names, via the existing `settings.set_api_key(...)` / `POST /api/system/credentials`.
- Relative imports are banned repo-wide (ruff `TID`) — always import absolute (`from artemis...`, `from apps...`).
- No new broad `except Exception` / bare-except handlers (quality ratchet baseline is fixed) — catch specific exception types only (`FileNotFoundError`, `ValueError`, `KeyError`, `pydantic.ValidationError`, etc.).
- Every new/edited Python file under `artemis/`, `apps/admin_console/` must stay lint-clean: line length 100, `ruff format`.

## Review Focus

- **`default` block save must not corrupt the rest of `artemis.jsonc`.** A user with hand-written comments, `presets`, and `nodes.<agent>` overrides saves an OpenAI config from the UI — those must come back byte-for-byte unchanged; only `default` changes. (Task 1 test: fixture JSONC with comments + presets + nodes, assert everything outside `default` is untouched.)
- **Clearing the Base URL field must not persist an empty string.** An empty/whitespace `api_base` must be *omitted* from the saved `default` block (so the provider's real default endpoint applies), never written as `"api_base": ""`. (Task 4 test.)
- **The Anthropic `base_url` fix must not regress the no-override case.** When `endpoint.api_base` is `None` (the common case — official Anthropic API), `ChatAnthropic` must be constructed exactly as before (no `base_url` kwarg at all, not `base_url=None`). (Task 3 test.)
- **A first-run / missing `default` block must fail loudly, not silently write a malformed file.** If `artemis.jsonc` has no top-level `"default"` key (shouldn't happen with the shipped config, but a hand-edited one could lack it), the save endpoint must return a clear 500 rather than inserting a broken block or throwing an unhandled 500 traceback. (Task 4 test.)
- **Legacy `default.provider` values must classify into the right Setup card on load**, not just the two new ones: `openrouter`/`xai`/`ollama`/`vllm`/`custom` → "OpenAI 兼容" card (they already share the `ChatOpenAI` dispatch branch), `anthropic` → "Anthropic 兼容", `google`/`vertexai`/anything else → Gemini card. (Task 6 covers the classification logic explicitly, including this repo's own current `config/artemis.jsonc` which has `default.provider: "custom"`.)

---

### Task 1: JSONC top-level block replace helper

**Files:**
- Modify: `artemis/utils/file.py`
- Test: `tests/unit/test_utils_file.py` (new)

**Interfaces:**
- Produces: `replace_jsonc_top_level_block(content: str, key: str, new_value: dict) -> str` — replaces one top-level `"<key>": { ... }` object in a JSONC document (matching braces, ignoring braces inside string literals) with `json.dumps(new_value, indent=2)`, reindented to the key's own line indentation. Raises `ValueError` if `key` isn't found as a top-level key or its braces are unbalanced. Everything outside that one block (comments, other keys) is preserved verbatim.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_utils_file.py
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

"""Unit tests for JSONC helpers in artemis/utils/file.py."""

import json

import pytest

from artemis.utils.file import replace_jsonc_top_level_block

SAMPLE = """{
  // ------------------------------------------------------------------
  // 1. Global Default Model
  // ------------------------------------------------------------------
  "default": {
    "provider": "custom",
    "model": "qwen3.8",
    "fallback": {
      "provider": "custom",
      "model": "qwen3.8"
    }
  },

  // ------------------------------------------------------------------
  // 2. Presets
  // ------------------------------------------------------------------
  "presets": {
    "gemini-flagship": {
      "provider": "google",
      "model": "gemini-3.8-flash"
    }
  },

  "nodes": {
    "planner": { "provider": "anthropic", "model": "claude-opus-4" }
  }
}
"""


def test_replaces_only_the_default_block():
    new_default = {"provider": "openai", "model": "gpt-4o", "api_base": "https://api.deepseek.com/v1"}

    result = replace_jsonc_top_level_block(SAMPLE, "default", new_default)

    # Comments and every other top-level key are byte-for-byte unchanged.
    assert "// 1. Global Default Model" in result
    assert "// 2. Presets" in result
    assert '"gemini-flagship"' in result
    assert '"planner": { "provider": "anthropic", "model": "claude-opus-4" }' in result

    # The default block itself now holds the new value.
    parsed = json.loads(
        __import__("artemis.utils.file", fromlist=["strip_json_comments"]).strip_json_comments(result)
    )
    assert parsed["default"] == new_default
    assert parsed["presets"]["gemini-flagship"]["provider"] == "google"
    assert parsed["nodes"]["planner"]["model"] == "claude-opus-4"


def test_omitting_api_base_drops_it_from_output():
    result = replace_jsonc_top_level_block(
        SAMPLE, "default", {"provider": "anthropic", "model": "claude-3-7-sonnet"}
    )

    parsed = json.loads(
        __import__("artemis.utils.file", fromlist=["strip_json_comments"]).strip_json_comments(result)
    )
    assert "api_base" not in parsed["default"]
    assert parsed["default"] == {"provider": "anthropic", "model": "claude-3-7-sonnet"}


def test_missing_key_raises_value_error():
    with pytest.raises(ValueError, match="not found"):
        replace_jsonc_top_level_block(SAMPLE, "nonexistent", {"a": 1})


def test_preserves_indentation_of_replacement_block():
    result = replace_jsonc_top_level_block(SAMPLE, "presets", {"a": {"provider": "openai", "model": "gpt-4o"}})

    # The replacement should be indented to match where "presets" itself sits (2 spaces).
    for line in result.splitlines():
        if '"a": {' in line:
            assert line.startswith("  ")
            break
    else:
        pytest.fail("Replacement block not found in output")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_utils_file.py -v`
Expected: FAIL with `ImportError: cannot import name 'replace_jsonc_top_level_block'`

- [ ] **Step 3: Implement the helper**

```python
# artemis/utils/file.py — add below load_jsonc, keep existing imports (json, re, IO)


def replace_jsonc_top_level_block(content: str, key: str, new_value: dict) -> str:
    """Replace one top-level ``"key": { ... }`` object in a JSONC document.

    Scans for matching braces while ignoring braces inside string literals, so
    it works on documents containing ``//`` comments and nested objects.
    Everything outside the located block — comments, other top-level keys —
    is preserved verbatim; only the located block's text is swapped out.

    Raises:
        ValueError: if ``key`` isn't found as a top-level key, or its braces
            are unbalanced (malformed document).
    """
    needle = f'"{key}"'
    key_idx = content.find(needle)
    if key_idx == -1:
        raise ValueError(f"Top-level key {key!r} not found in JSONC document.")

    brace_start = content.find("{", key_idx)
    if brace_start == -1:
        raise ValueError(f"No opening brace found for key {key!r}.")

    depth = 0
    brace_end = None
    in_string = False
    escape = False
    for i in range(brace_start, len(content)):
        c = content[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                brace_end = i
                break

    if brace_end is None:
        raise ValueError(f"Unbalanced braces while scanning key {key!r}.")

    line_start = content.rfind("\n", 0, key_idx) + 1
    indent = content[line_start:key_idx]
    new_block = json.dumps(new_value, indent=2).replace("\n", f"\n{indent}")

    return content[:brace_start] + new_block + content[brace_end + 1 :]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_utils_file.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format artemis/utils/file.py tests/unit/test_utils_file.py
uv run ruff check artemis/utils/file.py tests/unit/test_utils_file.py
git add artemis/utils/file.py tests/unit/test_utils_file.py
git commit -m "feat: add JSONC top-level block replace helper"
```

---

### Task 2: `api_base` field on `LLM` config, threaded to `ModelEndpoint`

**Files:**
- Modify: `artemis/config/llm.py`
- Modify: `artemis/services/llm.py:1060-1077` (`_resolve_endpoint`)
- Test: `tests/unit/test_config_package.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `LLM.api_base: str | None` (inherited by `LLMWithFallback`); `_resolve_endpoint(...)` now sets `ModelEndpoint(..., api_base=...)`. `ModelEndpoint.api_base` already exists (`artemis/llm/router.py:93`) — Task 3 consumes this for the Anthropic branch.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config_package.py`, near `test_llm_config_parsing_and_merging` (uses the same imports already at the top of that file: `deep_merge_llm_config`, `get_default_llm_config`, `LLMConfig`):

```python
def test_llm_config_api_base_threads_to_resolved_endpoint(monkeypatch, tmp_path):
    """A per-node api_base in config must reach the ModelEndpoint the router sees."""
    from artemis.config.llm import LLMConfig
    from artemis.context import ArtemisContext, DeviceContext, DevicePlatform
    from artemis.services.llm import _resolve_endpoint

    llm_cfg = get_default_llm_config()
    overrides = {
        "planner": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_base": "https://api.deepseek.com/v1",
            "fallback": {"provider": "openai", "model": "gpt-4o-mini"},
        }
    }
    merged: LLMConfig = deep_merge_llm_config(llm_cfg, overrides)
    assert merged.planner.api_base == "https://api.deepseek.com/v1"

    ctx = ArtemisContext(
        device=DeviceContext(serial="test", platform=DevicePlatform.ANDROID),
    )
    ctx.llm_config = merged

    endpoint = _resolve_endpoint(ctx, "planner")
    assert endpoint.api_base == "https://api.deepseek.com/v1"
```

If `ArtemisContext`/`DeviceContext` construction differs from this signature, use whatever minimal construction the neighboring tests in this file already use for `ArtemisContext` (see `test_checker_builder_and_context_propagation` a few functions below, which builds one) — match that pattern exactly rather than guessing new kwargs.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config_package.py::test_llm_config_api_base_threads_to_resolved_endpoint -v`
Expected: FAIL — `AttributeError: 'LLM' object has no attribute 'api_base'` (or a Pydantic "extra fields not permitted" error, depending on model config)

- [ ] **Step 3: Add the field and thread it through**

In `artemis/config/llm.py`, add to `class LLM(BaseModel)` (after `enable_grounding`):

```python
    enable_grounding: bool | None = None
    api_base: str | None = None
```

In `artemis/services/llm.py`, inside `_resolve_endpoint` (around line 1067), add `api_base` to the constructed `ModelEndpoint`:

```python
    return ModelEndpoint(
        provider=ModelProvider.from_string(provider_val),
        model_name=str(model_val),
        temperature=_get_val(cfg, "temperature", (int, float)) or 0.0,
        timeout_seconds=_get_val(cfg, "timeout", (int, float)) or 60.0,
        thinking_budget=_get_val(cfg, "thinking_budget", int),
        thinking_level=_get_val(cfg, "thinking_level", str),
        reasoning_effort=_get_val(cfg, "reasoning_effort", str),
        include_thoughts=_get_val(cfg, "include_thoughts", bool),
        enable_grounding=_get_val(cfg, "enable_grounding", bool) or False,
        api_base=_get_val(cfg, "api_base", str),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config_package.py::test_llm_config_api_base_threads_to_resolved_endpoint -v`
Expected: PASS

- [ ] **Step 5: Run the full config test file to check for regressions**

Run: `uv run pytest tests/unit/test_config_package.py -v`
Expected: All PASS

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format artemis/config/llm.py artemis/services/llm.py tests/unit/test_config_package.py
uv run ruff check artemis/config/llm.py artemis/services/llm.py tests/unit/test_config_package.py
git add artemis/config/llm.py artemis/services/llm.py tests/unit/test_config_package.py
git commit -m "feat: thread api_base through LLM config to ModelEndpoint"
```

---

### Task 3: Fix `ANTHROPIC` branch to honor `api_base`

**Files:**
- Modify: `artemis/llm/router.py:306-331`
- Test: `tests/unit/test_llm_grounding.py`

**Interfaces:**
- Consumes: `ModelEndpoint.api_base` (already exists; Task 2 is what makes config able to set it, but this task is independently testable by constructing a `ModelEndpoint` directly, exactly like the existing tests in this file do).
- Produces: no new public interface — fixes `ModelFactory.create_model` for `ModelProvider.ANTHROPIC` to pass `base_url` through to `ChatAnthropic`, matching the `OPENAI`/`OLLAMA`/`VLLM`/`CUSTOM` branches' existing pattern.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_llm_grounding.py` (which already imports `ModelEndpoint, ModelFactory, ModelProvider` from `artemis.llm.router`):

```python
def test_model_factory_anthropic_honors_custom_base_url():
    """A per-endpoint api_base must reach ChatAnthropic as anthropic_api_url."""
    ep = ModelEndpoint(
        provider=ModelProvider.ANTHROPIC,
        model_name="claude-3-7-sonnet-20250219",
        api_key="sk-ant-test-key",
        api_base="https://anthropic-gateway.internal/v1",
    )
    model = ModelFactory.create_model(ep)
    assert model.anthropic_api_url == "https://anthropic-gateway.internal/v1"


def test_model_factory_anthropic_default_base_url_when_unset():
    """Without an explicit api_base, ChatAnthropic must fall back to its own default
    (no api_base=None regression that would break the official Anthropic endpoint)."""
    ep = ModelEndpoint(
        provider=ModelProvider.ANTHROPIC,
        model_name="claude-3-7-sonnet-20250219",
        api_key="sk-ant-test-key",
    )
    model = ModelFactory.create_model(ep)
    assert model.anthropic_api_url == "https://api.anthropic.com"
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `uv run pytest tests/unit/test_llm_grounding.py::test_model_factory_anthropic_honors_custom_base_url tests/unit/test_llm_grounding.py::test_model_factory_anthropic_default_base_url_when_unset -v`
Expected: `test_model_factory_anthropic_honors_custom_base_url` FAILs (asserts `None == "https://anthropic-gateway.internal/v1"`... actually asserts the default `"https://api.anthropic.com"` was used instead); `test_model_factory_anthropic_default_base_url_when_unset` PASSes already (documents current-and-desired behavior for the unset case)

- [ ] **Step 3: Implement the fix**

In `artemis/llm/router.py`, in the `elif provider == ModelProvider.ANTHROPIC:` branch (~line 318), add `base_url` to the kwargs dict, filtered the same way the branch already filters `None`s:

```python
            kwargs = {
                "model": endpoint.model_name,
                "temperature": endpoint.temperature,
                "api_key": api_key,
                "timeout": endpoint.timeout_seconds,
                "base_url": endpoint.api_base,
            }
            budget = endpoint.thinking_budget
            if not budget and endpoint.reasoning_effort:
                effort_map = {"low": 2048, "medium": 8192, "high": 32768}
                budget = effort_map.get(endpoint.reasoning_effort.lower())
            if budget:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                kwargs["temperature"] = 1.0
            return ChatAnthropic(**{k: v for k, v in kwargs.items() if v is not None})
```

(Only the `kwargs = {...}` dict literal gains the `"base_url": endpoint.api_base,` line — the existing `{k: v for k, v in kwargs.items() if v is not None}` filter already strips it out when `api_base` is `None`, exactly like the `OPENAI` branch two cases above it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_llm_grounding.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format artemis/llm/router.py tests/unit/test_llm_grounding.py
uv run ruff check artemis/llm/router.py tests/unit/test_llm_grounding.py
git add artemis/llm/router.py tests/unit/test_llm_grounding.py
git commit -m "fix: pass api_base through to ChatAnthropic in ModelFactory"
```

---

### Task 4: Backend endpoint — `POST /api/system/model-config-env`

**Files:**
- Modify: `apps/admin_console/routers/system.py`
- Test: `tests/unit/admin_console/test_system_model_config_endpoint.py` (new)

**Interfaces:**
- Consumes: `replace_jsonc_top_level_block` from Task 1 (`artemis.utils.file`).
- Produces: `POST /api/system/model-config-env`, body `{"provider": "openai"|"anthropic", "model": str, "api_base": str | None}` → `200 {"status": "success", "message": str, "default_model": {"provider": ..., "model": ..., "api_base"?: ...}}`; `400` for an unsupported protocol or empty model; `500` if `artemis.jsonc` has no top-level `default` key.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/admin_console/test_system_model_config_endpoint.py
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

"""Unit tests for POST /api/system/model-config-env."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from apps.admin_console.server import app

SAMPLE_JSONC = """{
  // Global default model
  "default": {
    "provider": "google",
    "model": "gemini-3.8-flash"
  },

  "presets": {
    "gemini-flagship": { "provider": "google", "model": "gemini-3.8-flash" }
  }
}
"""

NO_DEFAULT_JSONC = """{
  "presets": {}
}
"""


@pytest.fixture
def jsonc_file(tmp_path: Path, monkeypatch) -> Path:
    config_path = tmp_path / "artemis.jsonc"
    config_path.write_text(SAMPLE_JSONC, encoding="utf-8")
    monkeypatch.setattr(
        "artemis.config.paths.get_config_path", lambda name: config_path
    )
    return config_path


@pytest.mark.asyncio
async def test_saves_openai_default_and_preserves_rest_of_file(jsonc_file: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env",
            json={
                "provider": "openai",
                "model": "deepseek-chat",
                "api_base": "https://api.deepseek.com/v1",
            },
        )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["default_model"] == {
        "provider": "openai",
        "model": "deepseek-chat",
        "api_base": "https://api.deepseek.com/v1",
    }

    saved = jsonc_file.read_text(encoding="utf-8")
    assert "// Global default model" in saved
    assert '"gemini-flagship"' in saved
    assert '"model": "deepseek-chat"' in saved


@pytest.mark.asyncio
async def test_empty_api_base_is_not_persisted(jsonc_file: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env",
            json={"provider": "anthropic", "model": "claude-3-7-sonnet", "api_base": "   "},
        )
    assert res.status_code == 200
    assert "api_base" not in res.json()["default_model"]
    assert "api_base" not in jsonc_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_rejects_unsupported_protocol(jsonc_file: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env",
            json={"provider": "google", "model": "gemini-3.8-flash"},
        )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_rejects_empty_model(jsonc_file: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env", json={"provider": "openai", "model": "  "}
        )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_missing_default_block_returns_clear_500(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "artemis.jsonc"
    config_path.write_text(NO_DEFAULT_JSONC, encoding="utf-8")
    monkeypatch.setattr(
        "artemis.config.paths.get_config_path", lambda name: config_path
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env", json={"provider": "openai", "model": "gpt-4o"}
        )
    assert res.status_code == 500
    assert "default" in res.json()["detail"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/admin_console/test_system_model_config_endpoint.py -v`
Expected: FAIL with `405 Method Not Allowed` (no `POST /model-config-env` route exists yet)

- [ ] **Step 3: Implement the endpoint**

In `apps/admin_console/routers/system.py`, add below the existing `get_model_config_and_env` function (after line ~493, before `@router.get("/server-status")`):

```python
class UpdateDefaultModelRequest(BaseModel):
    """Payload to set the global default model's provider/model/base URL."""

    provider: str = Field(description="Protocol family: 'openai' or 'anthropic'")
    model: str = Field(description="Model name/identifier for the target endpoint")
    api_base: str | None = Field(
        default=None,
        description="Custom base URL; omitted/blank uses the protocol's own default endpoint",
    )


@router.post("/model-config-env")
async def update_default_model_config(request: UpdateDefaultModelRequest):
    """Persist the global default model's provider/model/base URL into artemis.jsonc."""
    import json

    from artemis.config.paths import get_config_path
    from artemis.utils.file import replace_jsonc_top_level_block, strip_json_comments

    provider = request.provider.strip().lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported protocol '{provider}'. Must be 'openai' or 'anthropic'.",
        )

    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name cannot be empty.")

    try:
        config_path_obj = get_config_path("artemis.jsonc")
        content = config_path_obj.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"artemis.jsonc not found: {exc}")

    parsed = json.loads(strip_json_comments(content))
    if "default" not in parsed:
        raise HTTPException(
            status_code=500,
            detail="artemis.jsonc has no top-level 'default' block to update.",
        )

    new_default: dict = {"provider": provider, "model": model}
    api_base = (request.api_base or "").strip()
    if api_base:
        new_default["api_base"] = api_base

    try:
        new_content = replace_jsonc_top_level_block(content, "default", new_default)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    config_path_obj.write_text(new_content, encoding="utf-8")

    return {
        "status": "success",
        "message": f"Default model set to {provider}/{model}.",
        "default_model": new_default,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/admin_console/test_system_model_config_endpoint.py -v`
Expected: All PASS (6 passed)

- [ ] **Step 5: Run the broader admin_console suite for regressions**

Run: `uv run pytest tests/unit/admin_console -v`
Expected: All PASS

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format apps/admin_console/routers/system.py tests/unit/admin_console/test_system_model_config_endpoint.py
uv run ruff check apps/admin_console/routers/system.py tests/unit/admin_console/test_system_model_config_endpoint.py
git add apps/admin_console/routers/system.py tests/unit/admin_console/test_system_model_config_endpoint.py
git commit -m "feat: add POST /api/system/model-config-env to save default model"
```

---

### Task 5: `SystemService` — frontend client for the new endpoint

**Files:**
- Modify: `apps/showcase_ui/src/app/services/system.service.ts`
- Test: `apps/showcase_ui/src/app/services/system.service.spec.ts`

**Interfaces:**
- Consumes: `POST /api/system/model-config-env` from Task 4; existing `testApiKey(provider, apiKey, baseUrl?)` and `updateApiKey(provider, apiKey, persistToEnv?)` (both already generic — no changes needed).
- Produces: `SystemService.saveDefaultModel(provider: 'openai' | 'anthropic', model: string, apiBase: string | null): Observable<{status: string; message: string; default_model: Record<string, string>}>`. `ModelConfigEnvResponse.default_model` gains an optional `api_base?: string` field.

- [ ] **Step 1: Write the failing test**

Add to `apps/showcase_ui/src/app/services/system.service.spec.ts`, inside the existing `describe('SystemService readiness polling', ...)` block (reuses the `service`/`http` from the existing `beforeEach`):

```typescript
  it('saves the default model provider/model/base URL', () => {
    let result: any;
    service.saveDefaultModel('openai', 'deepseek-chat', 'https://api.deepseek.com/v1')
      .subscribe(res => result = res);

    const req = http.expectOne('/api/system/model-config-env');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      provider: 'openai',
      model: 'deepseek-chat',
      api_base: 'https://api.deepseek.com/v1'
    });
    req.flush({
      status: 'success',
      message: 'Default model set to openai/deepseek-chat.',
      default_model: { provider: 'openai', model: 'deepseek-chat', api_base: 'https://api.deepseek.com/v1' }
    });

    expect(result.status).toBe('success');
  });

  it('refreshes model config env after saving the default model', () => {
    service.saveDefaultModel('anthropic', 'claude-3-7-sonnet', null).subscribe();
    http.expectOne('/api/system/model-config-env').flush({
      status: 'success',
      message: 'ok',
      default_model: { provider: 'anthropic', model: 'claude-3-7-sonnet' }
    });

    // saveDefaultModel triggers a GET refresh of the same URL, same as updateApiKey does.
    http.expectOne('/api/system/model-config-env');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/showcase_ui && npm test -- --watch=false --browsers=ChromeHeadless --include='**/system.service.spec.ts'`
Expected: FAIL — `service.saveDefaultModel is not a function`

- [ ] **Step 3: Implement the method**

In `apps/showcase_ui/src/app/services/system.service.ts`, add after `updateApiKey` (before the closing `}` of the class, i.e. right before line 580's `}`):

```typescript
  /**
   * Persist the global default model's provider/model/base URL into artemis.jsonc.
   */
  public saveDefaultModel(
    provider: 'openai' | 'anthropic',
    model: string,
    apiBase: string | null
  ): Observable<{ status: string; message: string; default_model: Record<string, string> }> {
    return this.http.post<{ status: string; message: string; default_model: Record<string, string> }>(
      '/api/system/model-config-env',
      { provider, model, api_base: apiBase }
    ).pipe(
      tap({
        next: () => this.fetchModelConfigEnv().subscribe(),
        error: (err) => console.error(`Failed to save default model for ${provider}:`, err)
      })
    );
  }
```

Update the `ModelConfigEnvResponse` interface's `default_model` field (around line 586-595) to add `api_base`:

```typescript
  default_model: {
    provider?: string;
    model?: string;
    api_base?: string;
    thinking_level?: string;
    fallback?: {
      provider?: string;
      model?: string;
      thinking_level?: string;
    };
  };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/showcase_ui && npm test -- --watch=false --browsers=ChromeHeadless --include='**/system.service.spec.ts'`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/showcase_ui/src/app/services/system.service.ts apps/showcase_ui/src/app/services/system.service.spec.ts
git commit -m "feat: add SystemService.saveDefaultModel client for default-model save"
```

---

### Task 6: Home component — OpenAI/Anthropic setup cards + Advanced inspector

**Files:**
- Modify: `apps/showcase_ui/src/app/pages/home/home.component.ts`
- Modify: `apps/showcase_ui/src/app/pages/home/home.component.html`

**Interfaces:**
- Consumes: `SystemService.saveDefaultModel` (Task 5), `SystemService.testApiKey(provider, apiKey, baseUrl?)` and `SystemService.updateApiKey(provider, apiKey, persistToEnv?)` (unchanged, already generic), `SystemService.apiKeysMap()` (unchanged — already keyed by provider string, e.g. `'openai'`, `'anthropic'`), `ModelConfigEnvResponse.default_model.{provider,model,api_base}` (Task 5).
- Produces: no new public interfaces consumed elsewhere — this is the leaf UI.

No pre-existing spec file covers this component (`home.component.spec.ts` does not exist in the repo), so this task is implemented directly rather than test-first, and verified with a manual build + browser check in Step 6 — consistent with how the rest of this file's interactive-guide UI (ADB, emulator, OCR panels) is currently untested.

- [ ] **Step 1: Widen `modelSetupMode` and add per-protocol state signals**

In `apps/showcase_ui/src/app/pages/home/home.component.ts`, change line 126:

```typescript
  // Interactive guide tab for LLM / OCR credentials: 'gemini' | 'openai' | 'anthropic'
  public modelSetupMode = signal<'gemini' | 'openai' | 'anthropic'>('gemini');
  public showAdvancedInspector = signal<boolean>(false);
```

(Remove `showFullConfigFile` only if nothing else in the file still references it — grep first: `grep -n showFullConfigFile apps/showcase_ui/src/app/pages/home/home.component.ts apps/showcase_ui/src/app/pages/home/home.component.html`. If it's still used by the inspector's raw-jsonc-viewer toggle, leave it as-is; it's orthogonal to this change.)

After `isGeminiKeyEdited` (line 140), add the OpenAI and Anthropic state blocks, mirroring the Gemini block exactly but with `baseUrl`/`model` fields added:

```typescript
  // OpenAI-compatible Setup State
  public openaiBaseUrlInput = signal<string>('');
  public openaiModelInput = signal<string>('');
  public openaiKeyInput = signal<string>('');
  public showOpenaiKey = signal<boolean>(false);
  public isSavingOpenaiConfig = signal<boolean>(false);
  public isTestingOpenaiConfig = signal<boolean>(false);
  public openaiSaveMessage = signal<string | null>(null);
  public openaiSaveError = signal<string | null>(null);
  public isOpenaiKeyEdited = signal<boolean>(false);

  // Anthropic-compatible Setup State
  public anthropicBaseUrlInput = signal<string>('');
  public anthropicModelInput = signal<string>('');
  public anthropicKeyInput = signal<string>('');
  public showAnthropicKey = signal<boolean>(false);
  public isSavingAnthropicConfig = signal<boolean>(false);
  public isTestingAnthropicConfig = signal<boolean>(false);
  public anthropicSaveMessage = signal<string | null>(null);
  public anthropicSaveError = signal<string | null>(null);
  public isAnthropicKeyEdited = signal<boolean>(false);
```

- [ ] **Step 2: Add saved-key computed signals**

After `savedGeminiKey`/`isGeminiModified` (around line 474-481), add:

```typescript
  public savedOpenaiKey = computed<string>(() => this.apiKeysMap()['openai'] || '');
  public isOpenaiKeyModified = computed<boolean>(() =>
    this.openaiKeyInput().trim() !== this.savedOpenaiKey().trim()
  );

  public savedAnthropicKey = computed<string>(() => this.apiKeysMap()['anthropic'] || '');
  public isAnthropicKeyModified = computed<boolean>(() =>
    this.anthropicKeyInput().trim() !== this.savedAnthropicKey().trim()
  );
```

- [ ] **Step 3: Seed inputs from fetched config in the constructor effect and on mode switch**

In the constructor's `effect(...)` (around line 592-604), extend the same effect to also seed the openai/anthropic key inputs and, once, the base URL/model inputs from `modelConfigEnv()`:

```typescript
  constructor() {
    effect(() => {
      const keys = this.systemService.apiKeysMap();
      const current = this.systemService.currentApiKey();
      const googleKey = keys['google'] || current || '';
      const ocrKey = keys['ocr'] || '';
      const openaiKey = keys['openai'] || '';
      const anthropicKey = keys['anthropic'] || '';
      if (!this.isGeminiKeyEdited()) {
        this.geminiKeyInput.set(googleKey);
      }
      if (!this.isOcrKeyEdited()) {
        this.ocrKeyInput.set(ocrKey);
      }
      if (!this.isOpenaiKeyEdited()) {
        this.openaiKeyInput.set(openaiKey);
      }
      if (!this.isAnthropicKeyEdited()) {
        this.anthropicKeyInput.set(anthropicKey);
      }
    });

    effect(() => {
      const cfg = this.modelConfigEnv();
      if (!cfg) return;
      const provider = (cfg.default_model?.provider || '').toLowerCase();
      const model = cfg.default_model?.model || '';
      const apiBase = cfg.default_model?.api_base || '';
      // openrouter/xai/ollama/vllm/custom all share the OpenAI-compatible
      // ChatOpenAI dispatch branch in artemis/llm/router.py, so they all
      // land on the "OpenAI 兼容" card too.
      const openaiLikeProviders = ['openai', 'openrouter', 'xai', 'ollama', 'vllm', 'custom'];
      if (provider === 'anthropic') {
        this.anthropicModelInput.set(model);
        this.anthropicBaseUrlInput.set(apiBase);
      } else if (openaiLikeProviders.includes(provider)) {
        this.openaiModelInput.set(model);
        this.openaiBaseUrlInput.set(apiBase);
      }
    });
  }
```

- [ ] **Step 4: Replace `setModelSetupMode` and add save/test/clear methods**

Replace the existing `setModelSetupMode` (lines ~667-674):

```typescript
  public setModelSetupMode(mode: 'gemini' | 'openai' | 'anthropic'): void {
    this.modelSetupMode.set(mode);
  }

  public toggleAdvancedInspector(): void {
    this.showAdvancedInspector.update(v => !v);
    if (this.showAdvancedInspector()) {
      // Expanding the advanced panel means the user intends to manage
      // config/credentials by hand; don't block the launcher on the
      // automated credentials probe while they do that.
      this.systemService.setSkipCredentialsCheck(true);
      this.systemService.fetchModelConfigEnv().subscribe();
    }
  }
```

Add new methods after `testGeminiKey()` (around line 823), following the exact same shape as the Gemini save/test methods but parameterized by protocol:

```typescript
  public onOpenaiConfigChange(): void {
    this.isOpenaiKeyEdited.set(true);
    this.openaiSaveError.set(null);
    this.openaiSaveMessage.set(null);
  }

  public saveOpenaiConfig(): void {
    const model = this.openaiModelInput().trim();
    if (!model) {
      this.openaiSaveError.set('Model name is required.');
      return;
    }
    this.isSavingOpenaiConfig.set(true);
    this.openaiSaveError.set(null);
    this.openaiSaveMessage.set(null);

    const key = this.openaiKeyInput().trim();
    const baseUrl = this.openaiBaseUrlInput().trim() || null;

    const saveKey$ = key
      ? this.systemService.updateApiKey('openai', key, true)
      : null;

    const afterKey = () => {
      this.systemService.saveDefaultModel('openai', model, baseUrl).subscribe({
        next: (res) => {
          this.isSavingOpenaiConfig.set(false);
          this.isOpenaiKeyEdited.set(false);
          this.openaiSaveMessage.set(res?.message || '✓ OpenAI-compatible config saved.');
          setTimeout(() => this.openaiSaveMessage.set(null), 5000);
        },
        error: (err) => {
          this.isSavingOpenaiConfig.set(false);
          this.openaiSaveError.set(err?.error?.detail || err?.message || 'Failed to save default model.');
        }
      });
    };

    if (saveKey$) {
      saveKey$.subscribe({ next: afterKey, error: (err) => {
        this.isSavingOpenaiConfig.set(false);
        this.openaiSaveError.set(err?.error?.detail || err?.message || 'Failed to update OpenAI API key.');
      }});
    } else {
      afterKey();
    }
  }

  public testOpenaiConfig(): void {
    const key = this.openaiKeyInput().trim();
    if (!key) return;
    this.isTestingOpenaiConfig.set(true);
    this.openaiSaveError.set(null);
    this.openaiSaveMessage.set(null);

    this.systemService.testApiKey('openai', key, this.openaiBaseUrlInput().trim() || undefined).subscribe({
      next: (res) => {
        this.isTestingOpenaiConfig.set(false);
        if (res?.valid) {
          this.openaiSaveMessage.set(res?.message || '✓ OpenAI-compatible endpoint is valid!');
        } else {
          this.openaiSaveError.set(res?.message || 'Endpoint verification failed.');
        }
        setTimeout(() => this.openaiSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isTestingOpenaiConfig.set(false);
        this.openaiSaveError.set(err?.error?.detail || err?.message || 'Endpoint test failed.');
      }
    });
  }

  public onAnthropicConfigChange(): void {
    this.isAnthropicKeyEdited.set(true);
    this.anthropicSaveError.set(null);
    this.anthropicSaveMessage.set(null);
  }

  public saveAnthropicConfig(): void {
    const model = this.anthropicModelInput().trim();
    if (!model) {
      this.anthropicSaveError.set('Model name is required.');
      return;
    }
    this.isSavingAnthropicConfig.set(true);
    this.anthropicSaveError.set(null);
    this.anthropicSaveMessage.set(null);

    const key = this.anthropicKeyInput().trim();
    const baseUrl = this.anthropicBaseUrlInput().trim() || null;

    const saveKey$ = key
      ? this.systemService.updateApiKey('anthropic', key, true)
      : null;

    const afterKey = () => {
      this.systemService.saveDefaultModel('anthropic', model, baseUrl).subscribe({
        next: (res) => {
          this.isSavingAnthropicConfig.set(false);
          this.isAnthropicKeyEdited.set(false);
          this.anthropicSaveMessage.set(res?.message || '✓ Anthropic-compatible config saved.');
          setTimeout(() => this.anthropicSaveMessage.set(null), 5000);
        },
        error: (err) => {
          this.isSavingAnthropicConfig.set(false);
          this.anthropicSaveError.set(err?.error?.detail || err?.message || 'Failed to save default model.');
        }
      });
    };

    if (saveKey$) {
      saveKey$.subscribe({ next: afterKey, error: (err) => {
        this.isSavingAnthropicConfig.set(false);
        this.anthropicSaveError.set(err?.error?.detail || err?.message || 'Failed to update Anthropic API key.');
      }});
    } else {
      afterKey();
    }
  }

  public testAnthropicConfig(): void {
    const key = this.anthropicKeyInput().trim();
    if (!key) return;
    this.isTestingAnthropicConfig.set(true);
    this.anthropicSaveError.set(null);
    this.anthropicSaveMessage.set(null);

    this.systemService.testApiKey('anthropic', key, this.anthropicBaseUrlInput().trim() || undefined).subscribe({
      next: (res) => {
        this.isTestingAnthropicConfig.set(false);
        if (res?.valid) {
          this.anthropicSaveMessage.set(res?.message || '✓ Anthropic-compatible endpoint is valid!');
        } else {
          this.anthropicSaveError.set(res?.message || 'Endpoint verification failed.');
        }
        setTimeout(() => this.anthropicSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isTestingAnthropicConfig.set(false);
        this.anthropicSaveError.set(err?.error?.detail || err?.message || 'Endpoint test failed.');
      }
    });
  }

  public toggleOpenaiKeyVisibility(): void {
    this.showOpenaiKey.update(v => !v);
  }

  public toggleAnthropicKeyVisibility(): void {
    this.showAnthropicKey.update(v => !v);
  }
```

- [ ] **Step 5: Replace the Step 2 template markup**

In `apps/showcase_ui/src/app/pages/home/home.component.html`, replace the two-card row (lines 307-356) with a three-card row — keep Card 1 (Gemini, lines 309-336) byte-for-byte unchanged, replace Card 2 (lines 338-355, "Custom Configuration") with two new cards:

```html
    <div class="model-choice-cards-row">
      <!-- Card 1: Gemini (Recommended) -->
      <div class="choice-card" [class.selected]="modelSetupMode() === 'gemini'" (click)="setModelSetupMode('gemini')">
        <!-- unchanged: see existing lines 310-335 -->
      </div>

      <!-- Card 2: OpenAI-compatible -->
      <div class="choice-card" [class.selected]="modelSetupMode() === 'openai'" (click)="setModelSetupMode('openai')">
        <div class="choice-card-top">
          <div class="choice-radio">
            <span class="radio-dot" [class.checked]="modelSetupMode() === 'openai'"></span>
          </div>
          <div class="choice-icon-wrap icon-gear">
            <span class="material-symbols-outlined">api</span>
          </div>
          <div class="choice-text">
            <div class="choice-title-row">
              <span class="choice-title">OpenAI 兼容</span>
            </div>
            <p class="choice-desc">Any OpenAI-protocol endpoint: OpenAI, DeepSeek, OpenRouter, xAI, Ollama, vLLM, etc.</p>
          </div>
        </div>
      </div>

      <!-- Card 3: Anthropic-compatible -->
      <div class="choice-card" [class.selected]="modelSetupMode() === 'anthropic'" (click)="setModelSetupMode('anthropic')">
        <div class="choice-card-top">
          <div class="choice-radio">
            <span class="radio-dot" [class.checked]="modelSetupMode() === 'anthropic'"></span>
          </div>
          <div class="choice-icon-wrap icon-gear">
            <span class="material-symbols-outlined">smart_toy</span>
          </div>
          <div class="choice-text">
            <div class="choice-title-row">
              <span class="choice-title">Anthropic 兼容</span>
            </div>
            <p class="choice-desc">Any Anthropic-protocol endpoint: Anthropic Claude or a compatible gateway.</p>
          </div>
        </div>
      </div>
    </div>
```

Then change the dynamic panel's `@if (modelSetupMode() === 'gemini') { ... } @else { <custom-config-inspector> }` (line 359 / 542) into a three-way switch, keeping the existing Gemini block (lines 360-541, including its nested OCR box) unchanged under the `gemini` branch, and adding new `openai`/`anthropic` branches before it — reusing the exact same `credentials-input-box` / `unified-key-row` / `btn-unified-save` / `btn-unified-test` / `feedback-msg` CSS classes the Gemini block already uses, plus one extra text input for the model name and one for the base URL:

```html
    @if (modelSetupMode() === 'openai') {
    <div class="credentials-input-box">
      <div class="input-box-header">
        <div class="header-label">
          <span class="material-symbols-outlined label-icon">dns</span>
          <span>Base URL (optional — leave blank for api.openai.com):</span>
        </div>
      </div>
      <div class="unified-key-row">
        <div class="unified-key-wrapper">
          <input type="text" class="unified-key-input" [ngModel]="openaiBaseUrlInput()"
            (ngModelChange)="openaiBaseUrlInput.set($event); onOpenaiConfigChange()"
            placeholder="https://api.deepseek.com/v1" spellcheck="false" autocomplete="off" />
        </div>
      </div>
    </div>

    <div class="credentials-input-box">
      <div class="input-box-header">
        <div class="header-label">
          <span class="material-symbols-outlined label-icon">model_training</span>
          <span>Model:</span>
        </div>
      </div>
      <div class="unified-key-row">
        <div class="unified-key-wrapper">
          <input type="text" class="unified-key-input" [ngModel]="openaiModelInput()"
            (ngModelChange)="openaiModelInput.set($event); onOpenaiConfigChange()"
            placeholder="e.g. gpt-4o, deepseek-chat" spellcheck="false" autocomplete="off" />
        </div>
      </div>
    </div>

    <div class="credentials-input-box">
      <div class="input-box-header">
        <div class="header-label">
          <span class="material-symbols-outlined label-icon">vpn_key</span>
          <span>API Key:</span>
        </div>
      </div>
      <div class="unified-key-row">
        <div class="unified-key-wrapper">
          <span class="material-symbols-outlined key-prefix-icon">key</span>
          <input [type]="showOpenaiKey() ? 'text' : 'password'" class="unified-key-input"
            [class.is-masked]="!showOpenaiKey()" [ngModel]="openaiKeyInput()"
            (ngModelChange)="openaiKeyInput.set($event); onOpenaiConfigChange()"
            placeholder="Enter API Key..." spellcheck="false" autocomplete="off" />
          <button type="button" class="btn-icon-action" [title]="showOpenaiKey() ? 'Mask Key' : 'Show Plaintext'"
            (click)="toggleOpenaiKeyVisibility()">
            <span class="material-symbols-outlined">{{ showOpenaiKey() ? 'visibility_off' : 'visibility' }}</span>
          </button>
        </div>

        <button type="button" class="btn-unified-save" [class.btn-dirty]="isOpenaiKeyModified()"
          [disabled]="isSavingOpenaiConfig() || isTestingOpenaiConfig() || !openaiModelInput().trim()"
          (click)="saveOpenaiConfig()">
          @if (isSavingOpenaiConfig()) {
          <span class="material-symbols-outlined spin">sync</span>
          <span>Saving...</span>
          } @else {
          <span class="material-symbols-outlined">save</span>
          <span>Save & Apply</span>
          }
        </button>

        <button type="button" class="btn-unified-test" title="Test connectivity and key validity"
          [disabled]="isTestingOpenaiConfig() || isSavingOpenaiConfig() || !openaiKeyInput().trim()"
          (click)="testOpenaiConfig()">
          @if (isTestingOpenaiConfig()) {
          <span class="material-symbols-outlined spin">sync</span>
          <span>Testing...</span>
          } @else {
          <span class="material-symbols-outlined">network_check</span>
          <span>Test</span>
          }
        </button>
      </div>

      @if (openaiSaveMessage()) {
      <div class="feedback-msg success">
        <span class="material-symbols-outlined">check_circle</span>
        <span>{{ openaiSaveMessage() }}</span>
      </div>
      }
      @if (openaiSaveError()) {
      <div class="feedback-msg error">
        <span class="material-symbols-outlined">error</span>
        <span>{{ openaiSaveError() }}</span>
      </div>
      }
    </div>
    } @else if (modelSetupMode() === 'anthropic') {
    <div class="credentials-input-box">
      <div class="input-box-header">
        <div class="header-label">
          <span class="material-symbols-outlined label-icon">dns</span>
          <span>Base URL (optional — leave blank for api.anthropic.com):</span>
        </div>
      </div>
      <div class="unified-key-row">
        <div class="unified-key-wrapper">
          <input type="text" class="unified-key-input" [ngModel]="anthropicBaseUrlInput()"
            (ngModelChange)="anthropicBaseUrlInput.set($event); onAnthropicConfigChange()"
            placeholder="https://anthropic-gateway.internal/v1" spellcheck="false" autocomplete="off" />
        </div>
      </div>
    </div>

    <div class="credentials-input-box">
      <div class="input-box-header">
        <div class="header-label">
          <span class="material-symbols-outlined label-icon">model_training</span>
          <span>Model:</span>
        </div>
      </div>
      <div class="unified-key-row">
        <div class="unified-key-wrapper">
          <input type="text" class="unified-key-input" [ngModel]="anthropicModelInput()"
            (ngModelChange)="anthropicModelInput.set($event); onAnthropicConfigChange()"
            placeholder="e.g. claude-3-7-sonnet-20250219" spellcheck="false" autocomplete="off" />
        </div>
      </div>
    </div>

    <div class="credentials-input-box">
      <div class="input-box-header">
        <div class="header-label">
          <span class="material-symbols-outlined label-icon">vpn_key</span>
          <span>API Key:</span>
        </div>
      </div>
      <div class="unified-key-row">
        <div class="unified-key-wrapper">
          <span class="material-symbols-outlined key-prefix-icon">key</span>
          <input [type]="showAnthropicKey() ? 'text' : 'password'" class="unified-key-input"
            [class.is-masked]="!showAnthropicKey()" [ngModel]="anthropicKeyInput()"
            (ngModelChange)="anthropicKeyInput.set($event); onAnthropicConfigChange()"
            placeholder="Enter API Key..." spellcheck="false" autocomplete="off" />
          <button type="button" class="btn-icon-action" [title]="showAnthropicKey() ? 'Mask Key' : 'Show Plaintext'"
            (click)="toggleAnthropicKeyVisibility()">
            <span class="material-symbols-outlined">{{ showAnthropicKey() ? 'visibility_off' : 'visibility' }}</span>
          </button>
        </div>

        <button type="button" class="btn-unified-save" [class.btn-dirty]="isAnthropicKeyModified()"
          [disabled]="isSavingAnthropicConfig() || isTestingAnthropicConfig() || !anthropicModelInput().trim()"
          (click)="saveAnthropicConfig()">
          @if (isSavingAnthropicConfig()) {
          <span class="material-symbols-outlined spin">sync</span>
          <span>Saving...</span>
          } @else {
          <span class="material-symbols-outlined">save</span>
          <span>Save & Apply</span>
          }
        </button>

        <button type="button" class="btn-unified-test" title="Test connectivity and key validity"
          [disabled]="isTestingAnthropicConfig() || isSavingAnthropicConfig() || !anthropicKeyInput().trim()"
          (click)="testAnthropicConfig()">
          @if (isTestingAnthropicConfig()) {
          <span class="material-symbols-outlined spin">sync</span>
          <span>Testing...</span>
          } @else {
          <span class="material-symbols-outlined">network_check</span>
          <span>Test</span>
          }
        </button>
      </div>

      @if (anthropicSaveMessage()) {
      <div class="feedback-msg success">
        <span class="material-symbols-outlined">check_circle</span>
        <span>{{ anthropicSaveMessage() }}</span>
      </div>
      }
      @if (anthropicSaveError()) {
      <div class="feedback-msg error">
        <span class="material-symbols-outlined">error</span>
        <span>{{ anthropicSaveError() }}</span>
      </div>
      }
    </div>
    } @else {
    <!-- modelSetupMode() === 'gemini': existing block, unchanged (previously lines 360-541) -->
    }
```

Finally, replace the old binary `@if (modelSetupMode() === 'gemini') { ...gemini... } @else { <div class="custom-config-inspector">...inspector...</div> }` split: the inspector markup (previously under the `@else`, starting at the old line 544 `<div class="custom-config-inspector">`) moves **out** of that conditional entirely and becomes an always-present collapsible section placed after the `@if/@else if/@else` block above:

```html
    <!-- Advanced: raw artemis.jsonc / .env inspector, always reachable -->
    <div class="ocr-card-toggle-bar" (click)="toggleAdvancedInspector()">
      <div class="toggle-bar-left">
        <span class="material-symbols-outlined icon-ocr">tune</span>
        <div class="toggle-bar-titles">
          <span class="ocr-main-title">Advanced: view artemis.jsonc / .env</span>
        </div>
      </div>
      <div class="toggle-bar-right">
        <span class="material-symbols-outlined caret-icon">
          {{ showAdvancedInspector() ? 'expand_less' : 'expand_more' }}
        </span>
      </div>
    </div>
    @if (showAdvancedInspector()) {
      <div class="custom-config-inspector">
        <!-- unchanged inspector body, moved verbatim from the old @else branch -->
      </div>
    }
```

- [ ] **Step 6: Manual verification**

```bash
cd apps/showcase_ui && npm run build
```
Expected: build succeeds with no new template/type errors.

Then start the admin console (`uv run artemis ui --open` from repo root) and in the browser:
1. Confirm Step 2 shows three cards: Gemini, "OpenAI 兼容", "Anthropic 兼容".
2. Click "OpenAI 兼容": enter a Base URL, a Model name, and a (fake) API key; click "Test" (expect a network-error message, since the fake endpoint doesn't exist — confirms the test call reaches the backend and reports failure, not a frontend crash); click "Save & Apply"; confirm the success message appears and `config/artemis.jsonc`'s `default` block updated on disk (`cat config/artemis.jsonc | head -20`).
3. Switch to "Anthropic 兼容" and repeat.
4. Expand "Advanced: view artemis.jsonc / .env" and confirm it still renders the current file contents regardless of which of the three cards is selected.
5. Reload the page — confirm the card that matches the just-saved `default.provider` becomes preselected (this repo's own `config/artemis.jsonc` currently has `default.provider: "custom"`, which per Step 3's `openaiLikeProviders` list should preselect the "OpenAI 兼容" card — verify that specifically, since it's this repo's actual current state).

- [ ] **Step 7: Lint and commit**

```bash
cd apps/showcase_ui && npx eslint src/app/pages/home/home.component.ts --fix 2>/dev/null || true
git add apps/showcase_ui/src/app/pages/home/home.component.ts apps/showcase_ui/src/app/pages/home/home.component.html
git commit -m "feat: add OpenAI/Anthropic-compatible Setup cards and Advanced inspector"
```

---

### Task 7: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend deterministic suite**

Run: `make test`
Expected: all pass, no new failures relative to the `mobile-use` branch baseline before this plan started.

- [ ] **Step 2: Run lint and the quality ratchet**

Run: `make lint`
Expected: passes — no new `except Exception`/bare-except or `# type: ignore` introduced (Tasks 4 and 6 use only specific exception types, per Global Constraints).

- [ ] **Step 3: Run the frontend test suite**

Run: `cd apps/showcase_ui && npm test -- --watch=false --browsers=ChromeHeadless`
Expected: all pass, including the two new `system.service.spec.ts` cases from Task 5.

- [ ] **Step 4: Run pyright on the protected core**

Run: `make typecheck`
Expected: passes — confirm `artemis/config/llm.py` and `artemis/services/llm.py` are in `pyright-core.json`'s scope; if so this catches any type mismatch from the new `api_base` field before it ships.
