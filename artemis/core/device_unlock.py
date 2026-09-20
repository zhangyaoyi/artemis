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

"""Unlock a secure Android keyguard with a numeric PIN over ADB."""

import re
import time
from typing import Any

from pydantic import SecretStr

from artemis.sdk.types.exceptions import AgentError
from artemis.utils.logger import get_logger

logger = get_logger(__name__)

_PIN_PATTERN = re.compile(r"\d{4,16}")
_LOCK_PATTERN = re.compile(r"\bdeviceLocked=(true|1|false|0)\b", re.IGNORECASE)


def _is_locked(device: Any) -> bool | None:
    """Return the current user's lock state, or None when it cannot be determined."""
    try:
        output = str(device.shell("dumpsys trust"))
    except Exception:
        return None
    # The first entry belongs to the current user; later ones may be work profiles.
    match = _LOCK_PATTERN.search(output)
    if match is None:
        return None
    return match.group(1).lower() in {"true", "1"}


def unlock_with_pin(device: Any, pin: SecretStr, settle_seconds: float = 0.8) -> None:
    """Wake the screen, enter the PIN, and verify the device is unlocked.

    The PIN is never logged or included in error messages.

    Raises:
        AgentError: If the PIN is not 4-16 digits or the device stays locked.
    """
    secret = pin.get_secret_value()
    if not _PIN_PATTERN.fullmatch(secret):
        raise AgentError("ARTEMIS_DEVICE_UNLOCK_PIN must be a numeric PIN of 4-16 digits.")

    for attempt in (1, 2):
        logger.info(f"Unlocking device with configured PIN (attempt {attempt}).")
        device.shell("input keyevent KEYCODE_WAKEUP")
        device.shell("wm dismiss-keyguard")
        device.shell("input swipe 540 1800 540 600 200")
        time.sleep(settle_seconds)
        device.shell(f"input text {secret}")
        device.shell("input keyevent KEYCODE_ENTER")
        time.sleep(settle_seconds)
        if _is_locked(device) is not True:
            return

    raise AgentError(
        "Device is still locked after entering the configured PIN. "
        "Check ARTEMIS_DEVICE_UNLOCK_PIN and unlock the device manually."
    )
