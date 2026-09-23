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
    monkeypatch.setattr("artemis.config.paths.get_config_path", lambda name: config_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        res = await ac.post(
            "/api/system/model-config-env", json={"provider": "openai", "model": "gpt-4o"}
        )
    assert res.status_code == 500
    assert "default" in res.json()["detail"].lower()
