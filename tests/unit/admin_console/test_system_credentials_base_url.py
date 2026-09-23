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

"""POST /api/system/credentials must validate a key against its own base_url,
not always the provider's official endpoint -- otherwise a valid key for a
custom OpenAI/Anthropic-compatible endpoint (DeepSeek, OpenRouter, a gateway)
is rejected as invalid and the Setup card's Save & Apply can never succeed."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from apps.admin_console.server import app


@pytest.mark.asyncio
async def test_update_credentials_passes_base_url_to_validation():
    with patch(
        "artemis.utils.credentials_validator.validate_api_key",
        new=AsyncMock(return_value=(True, "ok")),
    ) as mock_validate:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
            res = await ac.post(
                "/api/system/credentials",
                json={
                    "provider": "openai",
                    "api_key": "sk-deepseek-test-key",
                    "persist_to_env": False,
                    "base_url": "https://api.deepseek.com/v1",
                },
            )

    assert res.status_code == 200
    mock_validate.assert_awaited_once_with(
        provider="openai", api_key="sk-deepseek-test-key", base_url="https://api.deepseek.com/v1"
    )
