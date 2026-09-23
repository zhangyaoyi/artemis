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

import json
from typing import IO


def strip_json_comments(text: str) -> str:
    """Strip ``//`` and ``/* */`` comments from a JSONC document.

    String-literal aware: a ``//`` inside a JSON string value (e.g. a URL
    like ``"https://api.example.com"``) is left untouched rather than being
    mistaken for a line comment.
    """
    result = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        c = text[i]
        if in_string:
            result.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            result.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            newline_idx = text.find("\n", i)
            i = n if newline_idx == -1 else newline_idx
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end_idx = text.find("*/", i + 2)
            i = n if end_idx == -1 else end_idx + 2
            continue
        result.append(c)
        i += 1
    return "".join(result)


def load_jsonc(file: IO) -> dict:
    return json.loads(strip_json_comments(file.read()))


def _mask_comments(text: str) -> str:
    """Like ``strip_json_comments``, but replaces comment text with spaces
    (newlines kept) instead of removing it, so character offsets into the
    original document are preserved. Lets callers scan the masked text for
    structure (strings/braces) and then slice the *original* text by the
    same indices."""
    result = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        c = text[i]
        if in_string:
            result.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            result.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            newline_idx = text.find("\n", i)
            end = n if newline_idx == -1 else newline_idx
            result.append(" " * (end - i))
            i = end
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end_idx = text.find("*/", i + 2)
            end = n if end_idx == -1 else end_idx + 2
            segment = text[i:end]
            result.append("".join(ch if ch == "\n" else " " for ch in segment))
            i = end
            continue
        result.append(c)
        i += 1
    return "".join(result)


def replace_jsonc_top_level_block(content: str, key: str, new_value: dict) -> str:
    """Replace one top-level ``"key": { ... }`` object in a JSONC document.

    Comment- and string-aware: scans a comment-masked copy of the document so
    that a key name mentioned inside a ``//``/``/* */`` comment, or braces
    written inside a comment (e.g. a commented-out fragment), never affect
    where the real key or its matching closing brace are found. Only a
    genuine top-level (depth-1) ``"key": { ... }`` is matched. Everything
    outside the located block — comments, other top-level keys — is
    preserved verbatim; only the located block's text is swapped out.

    Raises:
        ValueError: if ``key`` isn't found as a real top-level key, or its
            braces are unbalanced (malformed document).
    """
    masked = _mask_comments(content)
    needle = f'"{key}"'
    n = len(masked)

    depth = 0
    in_string = False
    escape = False
    key_idx = None
    i = 0
    while i < n:
        c = masked[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            if depth == 1 and masked.startswith(needle, i):
                after = i + len(needle)
                j = after
                while j < n and masked[j] in " \t\r\n":
                    j += 1
                if j < n and masked[j] == ":":
                    key_idx = i
                    break
            in_string = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1

    if key_idx is None:
        raise ValueError(f"Top-level key {key!r} not found in JSONC document.")

    brace_start = masked.find("{", key_idx)
    if brace_start == -1:
        raise ValueError(f"No opening brace found for key {key!r}.")

    depth = 0
    brace_end = None
    in_string = False
    escape = False
    for i in range(brace_start, n):
        c = masked[i]
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
