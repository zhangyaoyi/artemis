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

from artemis.utils.file import replace_jsonc_top_level_block, strip_json_comments

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


def test_strip_json_comments_preserves_double_slash_inside_string_values():
    """A URL like https://... inside a JSON string must survive comment
    stripping — it is not a `//` line comment just because it looks like one."""
    text = '{\n  "api_base": "https://api.deepseek.com/v1" // trailing comment\n}'

    result = strip_json_comments(text)

    assert json.loads(result) == {"api_base": "https://api.deepseek.com/v1"}


def test_replaces_only_the_default_block():
    new_default = {
        "provider": "openai",
        "model": "gpt-4o",
        "api_base": "https://api.deepseek.com/v1",
    }

    result = replace_jsonc_top_level_block(SAMPLE, "default", new_default)

    # Comments and every other top-level key are byte-for-byte unchanged.
    assert "// 1. Global Default Model" in result
    assert "// 2. Presets" in result
    assert '"gemini-flagship"' in result
    assert '"planner": { "provider": "anthropic", "model": "claude-opus-4" }' in result

    # The default block itself now holds the new value.
    parsed = json.loads(
        __import__("artemis.utils.file", fromlist=["strip_json_comments"]).strip_json_comments(
            result
        )
    )
    assert parsed["default"] == new_default
    assert parsed["presets"]["gemini-flagship"]["provider"] == "google"
    assert parsed["nodes"]["planner"]["model"] == "claude-opus-4"


def test_omitting_api_base_drops_it_from_output():
    result = replace_jsonc_top_level_block(
        SAMPLE, "default", {"provider": "anthropic", "model": "claude-3-7-sonnet"}
    )

    parsed = json.loads(
        __import__("artemis.utils.file", fromlist=["strip_json_comments"]).strip_json_comments(
            result
        )
    )
    assert "api_base" not in parsed["default"]
    assert parsed["default"] == {"provider": "anthropic", "model": "claude-3-7-sonnet"}


def test_missing_key_raises_value_error():
    with pytest.raises(ValueError, match="not found"):
        replace_jsonc_top_level_block(SAMPLE, "nonexistent", {"a": 1})


def test_preserves_indentation_of_replacement_block():
    result = replace_jsonc_top_level_block(
        SAMPLE, "presets", {"a": {"provider": "openai", "model": "gpt-4o"}}
    )

    # The replacement should be indented to match where "presets" itself sits (2 spaces).
    for line in result.splitlines():
        if '"a": {' in line:
            assert line.startswith("  ")
            break
    else:
        pytest.fail("Replacement block not found in output")
