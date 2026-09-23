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
    monkeypatch.setattr("artemis.config.paths.get_config_path", lambda name: config_path)
    return config_path


@pytest.mark.asyncio
async def test_saved_default_block_parses_into_a_valid_llm_config(jsonc_file: Path):
    """The saved `default` block must round-trip through the real config loader:
    LLMWithFallback.fallback is a required field, so a save that omits it makes
    every agent node fail LLMConfig validation and every task fail to start."""
    from artemis.config.llm import LLMConfig
    from artemis.utils.file import strip_json_comments

    import json as jsonlib

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

    saved = jsonc_file.read_text(encoding="utf-8")
    parsed = jsonlib.loads(strip_json_comments(saved))

    from artemis.config.llm import _expand_default_into_nodes

    expanded = _expand_default_into_nodes(parsed)
    llm_config = LLMConfig.model_validate(expanded)

    assert llm_config.planner.provider == "openai"
    assert llm_config.planner.model == "deepseek-chat"
    assert llm_config.planner.api_base == "https://api.deepseek.com/v1"
    assert llm_config.planner.fallback is not None
    assert llm_config.planner.fallback.provider == "openai"


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
        "fallback": {
            "provider": "openai",
            "model": "deepseek-chat",
            "api_base": "https://api.deepseek.com/v1",
        },
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
async def test_malformed_jsonc_returns_clear_500_instead_of_crashing(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "artemis.jsonc"
    config_path.write_text('{ "default": { "provider": "google" ', encoding="utf-8")
    monkeypatch.setattr("artemis.config.paths.get_config_path", lambda name: config_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env", json={"provider": "openai", "model": "gpt-4o"}
        )
    assert res.status_code == 500
    assert "artemis.jsonc" in res.json()["detail"].lower() or "json" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_does_not_write_if_the_rewritten_content_fails_to_verify(
    jsonc_file: Path, monkeypatch
):
    """If replace_jsonc_top_level_block ever produced output that doesn't
    round-trip back to the intended default block, the endpoint must refuse
    to write it rather than silently corrupting the user's config file."""
    import artemis.utils.file as file_utils

    original_content = jsonc_file.read_text(encoding="utf-8")
    monkeypatch.setattr(
        file_utils, "replace_jsonc_top_level_block", lambda content, key, value: "{ not valid json"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env", json={"provider": "openai", "model": "gpt-4o"}
        )
    assert res.status_code == 500
    assert jsonc_file.read_text(encoding="utf-8") == original_content


@pytest.mark.asyncio
async def test_wheel_install_writes_to_app_dir_not_the_bundled_template(
    tmp_path: Path, monkeypatch
):
    """In a wheel install, get_config_path() can resolve to the immutable
    bundled template. The save must go to the writable app dir instead of
    attempting (and possibly failing, or silently not persisting) a write to
    site-packages."""
    bundled_path = tmp_path / "bundled" / "artemis.jsonc"
    bundled_path.parent.mkdir(parents=True)
    bundled_path.write_text(SAMPLE_JSONC, encoding="utf-8")

    app_dir = tmp_path / "app_dir"

    monkeypatch.setattr("artemis.config.paths.get_config_path", lambda name: bundled_path)
    monkeypatch.setattr("artemis.config.paths._use_user_app_dir", lambda: True)
    monkeypatch.setattr("artemis.config.paths.get_app_dir", lambda: app_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env",
            json={"provider": "openai", "model": "gpt-4o"},
        )
    assert res.status_code == 200

    # The bundled template is untouched; the app dir now has the saved config.
    assert '"provider": "google"' in bundled_path.read_text(encoding="utf-8")
    written = (app_dir / "artemis.jsonc").read_text(encoding="utf-8")
    assert '"model": "gpt-4o"' in written
    assert '"gemini-flagship"' in written


@pytest.mark.asyncio
async def test_missing_default_block_returns_clear_500(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "artemis.jsonc"
    config_path.write_text(NO_DEFAULT_JSONC, encoding="utf-8")
    monkeypatch.setattr("artemis.config.paths.get_config_path", lambda name: config_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env", json={"provider": "openai", "model": "gpt-4o"}
        )
    assert res.status_code == 500
    assert "default" in res.json()["detail"].lower()
