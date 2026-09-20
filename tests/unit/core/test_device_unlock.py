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

"""Tests for ADB PIN device unlock."""

from unittest.mock import MagicMock

from pydantic import SecretStr
import pytest

from artemis.core.device_unlock import unlock_with_pin
from artemis.sdk.types.exceptions import AgentError

LOCKED = 'User "Owner" (id=0): deviceLocked=1\n'
UNLOCKED = 'User "Owner" (id=0): deviceLocked=0\n'


def _device(*trust_states: str) -> MagicMock:
    device = MagicMock()
    states = iter(trust_states)
    device.shell.side_effect = lambda cmd: next(states) if cmd == "dumpsys trust" else ""
    return device


def _commands(device: MagicMock) -> list[str]:
    return [c.args[0] for c in device.shell.call_args_list]


def test_unlock_sends_pin_over_adb():
    device = _device(UNLOCKED)
    unlock_with_pin(device, SecretStr("1234"), settle_seconds=0)
    cmds = _commands(device)
    assert "input keyevent KEYCODE_WAKEUP" in cmds
    assert "input text 1234" in cmds
    assert cmds.index("input text 1234") < cmds.index("input keyevent KEYCODE_ENTER")


def test_unlock_fails_when_still_locked_and_hides_pin():
    device = _device(LOCKED, LOCKED)
    with pytest.raises(AgentError) as exc:
        unlock_with_pin(device, SecretStr("1234"), settle_seconds=0)
    assert "1234" not in str(exc.value)


def test_unlock_retries_once():
    device = _device(LOCKED, UNLOCKED)
    unlock_with_pin(device, SecretStr("1234"), settle_seconds=0)
    assert _commands(device).count("input text 1234") == 2


@pytest.mark.parametrize("pin", ["", "12a4", "12 4", "123"])
def test_invalid_pin_rejected_without_touching_device(pin):
    device = _device()
    with pytest.raises(AgentError) as exc:
        unlock_with_pin(device, SecretStr(pin), settle_seconds=0)
    device.shell.assert_not_called()
    assert pin not in str(exc.value) or pin == ""
