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

"""Preset Task Catalog & Dynamic Recommendation Engine for Artemis."""

from typing import Any, Literal
from pydantic import BaseModel, Field

from datetime import datetime, timezone, UTC
import uuid

try:
    from admin_console.database.repositories.task_preset_repository import (
        TaskPresetRepository,
        task_preset_repository,
    )
except ImportError:
    from apps.admin_console.database.repositories.task_preset_repository import (
        TaskPresetRepository,
        task_preset_repository,
    )

try:
    from admin_console.database.repositories.app_repository import (
        AppRepository,
        app_repository as default_app_repository,
    )
except ImportError:
    from apps.admin_console.database.repositories.app_repository import (
        AppRepository,
        app_repository as default_app_repository,
    )


class AppInfo(BaseModel):
    """Application metadata."""

    name: str
    pkg: str
    category: str = "general"


class TaskPreset(BaseModel):
    """Smart suggestion task definition."""

    id: str
    title: str
    description: str
    goal: str
    profile: Literal["flash", "pro"]
    category: Literal["flash", "pro", "cross_app", "monitor"]
    tag: str
    apps: list[AppInfo]
    required_packages: list[str] = Field(default_factory=list)
    match_mode: Literal["any", "all"] = "any"
    priority: int = 50


# ============================================================================
# APP PACKAGE REGISTRY
# ============================================================================

APP_REGISTRY: dict[str, dict[str, str]] = {
    # Google Suite & System
    "com.google.android.apps.maps": {"name": "Maps", "category": "navigation"},
    "com.google.android.gm": {"name": "Gmail", "category": "productivity"},
    "com.android.chrome": {"name": "Chrome", "category": "browser"},
    "com.google.android.youtube": {
        "name": "YouTube",
        "category": "entertainment",
    },
    "com.android.settings": {"name": "Settings", "category": "system"},
    "com.google.android.deskclock": {"name": "Clock", "category": "utility"},
    "com.android.deskclock": {"name": "Clock", "category": "utility"},
    "com.google.android.calculator": {
        "name": "Calculator",
        "category": "utility",
    },
    "com.android.calculator2": {"name": "Calculator", "category": "utility"},
    "com.google.android.apps.photos": {
        "name": "Photos",
        "category": "media",
    },
    "com.google.android.calendar": {
        "name": "Calendar",
        "category": "productivity",
    },
    "com.google.android.keep": {
        "name": "Keep Notes",
        "category": "productivity",
    },
    "com.android.vending": {"name": "Play Store", "category": "tools"},
    "com.google.android.apps.messaging": {
        "name": "Messages",
        "category": "communication",
    },
    # Popular Ecosystem Apps
    "com.tencent.mm": {"name": "WeChat", "category": "social"},
    "com.xingin.xhs": {"name": "Xiaohongshu", "category": "social"},
    "com.sankuai.meituan": {"name": "Meituan", "category": "lifestyle"},
    "com.dianping.v1": {"name": "Dianping", "category": "lifestyle"},
    "tv.danmaku.bili": {"name": "Bilibili", "category": "entertainment"},
    "com.eg.android.AlipayGphone": {
        "name": "Alipay",
        "category": "finance",
    },
    "com.netease.cloudmusic": {
        "name": "NetEase Music",
        "category": "entertainment",
    },
    "com.spotify.music": {"name": "Spotify", "category": "entertainment"},
}


# ============================================================================
# CURATED TASK PRESET LIBRARY (1-2 curated tasks per common app)
# ============================================================================

PRESET_TASK_CATALOG: list[TaskPreset] = [
    # 1. Google Maps
    TaskPreset(
        id="maps_coffee",
        title="Find Specialty Coffee",
        description="Search nearby top-rated cafes in Google Maps",
        goal="Open Google Maps, search for top-rated specialty coffee shops nearby, and view the top result details.",
        profile="flash",
        category="flash",
        tag="Maps",
        apps=[
            AppInfo(
                name="Maps",
                pkg="com.google.android.apps.maps",
                category="navigation",
            )
        ],
        required_packages=["com.google.android.apps.maps"],
        priority=95,
    ),
    TaskPreset(
        id="pro_commute_share",
        title="Commute ETA & Message Draft",
        description="Check transit time on Maps and draft arrival ETA in Messages",
        goal="Open Google Maps to check commute time to the International Airport, calculate arrival time, then open Messages and draft an ETA text message.",
        profile="pro",
        category="cross_app",
        tag="Maps + Messages",
        apps=[
            AppInfo(
                name="Maps",
                pkg="com.google.android.apps.maps",
                category="navigation",
            ),
            AppInfo(
                name="Messages",
                pkg="com.google.android.apps.messaging",
                category="communication",
            ),
        ],
        required_packages=["com.google.android.apps.maps", "com.google.android.apps.messaging"],
        match_mode="all",
        priority=92,
    ),
    # 2. Gmail
    TaskPreset(
        id="gmail_receipts",
        title="Search Order Receipts",
        description="Find recent flight or delivery confirmation emails in Gmail",
        goal="Open Gmail and search for recent flight or package delivery confirmation emails.",
        profile="flash",
        category="flash",
        tag="Gmail",
        apps=[AppInfo(name="Gmail", pkg="com.google.android.gm", category="productivity")],
        required_packages=["com.google.android.gm"],
        priority=90,
    ),
    TaskPreset(
        id="pro_email_to_calendar",
        title="Email Itinerary to Calendar",
        description="Extract flight or event dates from Gmail and schedule in Calendar",
        goal="Open Gmail to find the latest event invitation or itinerary, extract dates and location, then open Google Calendar and create a corresponding calendar event.",
        profile="pro",
        category="cross_app",
        tag="Gmail + Calendar",
        apps=[
            AppInfo(name="Gmail", pkg="com.google.android.gm", category="productivity"),
            AppInfo(
                name="Calendar",
                pkg="com.google.android.calendar",
                category="productivity",
            ),
        ],
        required_packages=["com.google.android.gm"],
        priority=94,
    ),
    # 3. Chrome
    TaskPreset(
        id="chrome_research",
        title="Search AI News Breakthroughs",
        description="Search latest multimodal AI developments in Chrome browser",
        goal="Open Chrome browser and search for latest breakthroughs in multimodal mobile AI agents.",
        profile="flash",
        category="flash",
        tag="Chrome",
        apps=[AppInfo(name="Chrome", pkg="com.android.chrome", category="browser")],
        required_packages=["com.android.chrome"],
        priority=88,
    ),
    TaskPreset(
        id="pro_research_keep",
        title="Product Research & Notes Note",
        description="Compare top 3 headphones on Chrome and record comparison in Keep",
        goal="Open Chrome, research top 3 noise-cancelling headphones comparing price and battery life, then write a structured comparison summary note in Keep Notes.",
        profile="pro",
        category="pro",
        tag="Chrome + Keep",
        apps=[
            AppInfo(name="Chrome", pkg="com.android.chrome", category="browser"),
            AppInfo(
                name="Keep Notes",
                pkg="com.google.android.keep",
                category="productivity",
            ),
        ],
        required_packages=["com.android.chrome"],
        priority=91,
    ),
    # 4. YouTube
    TaskPreset(
        id="youtube_lofi",
        title="Play Lo-Fi Music Radio",
        description="Search and play a Lo-Fi hip hop live stream on YouTube",
        goal='Open YouTube, search for "Lofi hip hop beats relaxing radio" and tap on the live stream.',
        profile="flash",
        category="flash",
        tag="YouTube",
        apps=[
            AppInfo(
                name="YouTube",
                pkg="com.google.android.youtube",
                category="entertainment",
            )
        ],
        required_packages=["com.google.android.youtube"],
        priority=85,
    ),
    # 5. Settings
    TaskPreset(
        id="settings_display_wifi",
        title="Dark Mode & Wi-Fi Check",
        description="Toggle dark theme and verify network connection in Settings",
        goal="Open Settings app, navigate to Display settings, ensure Dark theme is enabled, and check Wi-Fi connection status.",
        profile="flash",
        category="flash",
        tag="Settings",
        apps=[AppInfo(name="Settings", pkg="com.android.settings", category="system")],
        required_packages=["com.android.settings"],
        priority=87,
    ),
    TaskPreset(
        id="pro_settings_qa",
        title="Subsystem Health & Crash Probe",
        description="Traverse Settings submenus to verify screens and check for crash dialogs",
        goal="Explore Settings submenus (Network, Connected devices, Apps, Battery, Storage), verify each screen loads properly without ANR or crash dialogs, and summarize results.",
        profile="pro",
        category="monitor",
        tag="Settings QA",
        apps=[AppInfo(name="Settings", pkg="com.android.settings", category="system")],
        required_packages=["com.android.settings"],
        priority=93,
    ),
    # 6. Clock
    TaskPreset(
        id="clock_timer",
        title="25-Min Pomodoro Timer",
        description="Start a 25-minute focus countdown timer in Clock app",
        goal="Open Clock app, switch to Timer tab, set 25 minutes and start the countdown timer.",
        profile="flash",
        category="flash",
        tag="Clock",
        apps=[AppInfo(name="Clock", pkg="com.google.android.deskclock", category="utility")],
        required_packages=["com.google.android.deskclock", "com.android.deskclock"],
        priority=86,
    ),
    # 7. Calculator
    TaskPreset(
        id="calc_gratuity",
        title="Split Bill & Calculate Tip",
        description="Calculate 18% gratuity on $186.40 for 3 people in Calculator",
        goal="Open Calculator and calculate 18% tip on a bill of $186.40, then divide by 3 people.",
        profile="flash",
        category="flash",
        tag="Calculator",
        apps=[
            AppInfo(
                name="Calculator",
                pkg="com.google.android.calculator",
                category="utility",
            )
        ],
        required_packages=["com.google.android.calculator", "com.android.calculator2"],
        priority=84,
    ),
    # 8. Photos
    TaskPreset(
        id="photos_inspect",
        title="Inspect Recent Screenshot",
        description="Open Google Photos and review the latest screenshot taken",
        goal="Open Google Photos and view the most recent screenshot in the screenshots album.",
        profile="flash",
        category="flash",
        tag="Photos",
        apps=[
            AppInfo(
                name="Photos",
                pkg="com.google.android.apps.photos",
                category="media",
            )
        ],
        required_packages=["com.google.android.apps.photos"],
        priority=82,
    ),
    # 9. WeChat
    TaskPreset(
        id="wechat_browse",
        title="Check WeChat Messages",
        description="Open WeChat and view top recent chat conversations",
        goal="Open WeChat and view the top recent chat messages.",
        profile="flash",
        category="flash",
        tag="WeChat",
        apps=[AppInfo(name="WeChat", pkg="com.tencent.mm", category="social")],
        required_packages=["com.tencent.mm"],
        priority=89,
    ),
    TaskPreset(
        id="pro_wechat_to_calendar",
        title="WeChat Notice to Calendar",
        description="Extract meeting notice from WeChat chat and add to Calendar",
        goal="Open WeChat, locate the latest meeting announcement or event message in the top chat, extract the time and topic, then open Calendar and schedule an event.",
        profile="pro",
        category="cross_app",
        tag="WeChat + Calendar",
        apps=[
            AppInfo(name="WeChat", pkg="com.tencent.mm", category="social"),
            AppInfo(
                name="Calendar",
                pkg="com.google.android.calendar",
                category="productivity",
            ),
        ],
        required_packages=["com.tencent.mm"],
        priority=93,
    ),
    # 10. Xiaohongshu
    TaskPreset(
        id="xhs_coffee_guide",
        title="RED Cafe Guide Search",
        description="Search trending specialty cafe reviews on Xiaohongshu",
        goal="Open Xiaohongshu, search for top-rated specialty coffee shops, and view the top post.",
        profile="flash",
        category="flash",
        tag="Xiaohongshu",
        apps=[AppInfo(name="Xiaohongshu", pkg="com.xingin.xhs", category="social")],
        required_packages=["com.xingin.xhs"],
        priority=87,
    ),
    # 11. Meituan / Dianping
    TaskPreset(
        id="meituan_ramen_search",
        title="Meituan Food Search",
        description="Search top-rated Ramen nearby on Meituan or Dianping",
        goal="Open Meituan or Dianping, search for top-rated Ramen nearby, and view top restaurant rating.",
        profile="flash",
        category="flash",
        tag="Meituan",
        apps=[AppInfo(name="Meituan", pkg="com.sankuai.meituan", category="lifestyle")],
        required_packages=["com.sankuai.meituan", "com.dianping.v1"],
        priority=86,
    ),
    # 12. Bilibili
    TaskPreset(
        id="bilibili_stream",
        title="Bilibili Tech Video",
        description="Search and play an AI Agent tutorial video on Bilibili",
        goal='Open Bilibili, search for "AI Agent Architecture", and play the top matching video.',
        profile="flash",
        category="flash",
        tag="Bilibili",
        apps=[
            AppInfo(
                name="Bilibili",
                pkg="tv.danmaku.bili",
                category="entertainment",
            )
        ],
        required_packages=["tv.danmaku.bili"],
        priority=85,
    ),
    # 13. Play Store
    TaskPreset(
        id="pro_playstore_review",
        title="Play Store App Review Study",
        description="Compare top task management apps and ratings on Google Play",
        goal="Open Google Play Store, search for top rated task management apps, compare ratings and latest user reviews of the top 2 candidates, and record recommendations.",
        profile="pro",
        category="pro",
        tag="Play Store",
        apps=[AppInfo(name="Play Store", pkg="com.android.vending", category="tools")],
        required_packages=["com.android.vending"],
        priority=88,
    ),
]


# ============================================================================
# RECOMMENDATION ENGINE
# ============================================================================


def _builtin_seed_rows() -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    rows = []
    for task in PRESET_TASK_CATALOG:
        row = task.model_dump()
        row["is_builtin"] = True
        row["created_at"] = now
        row["updated_at"] = now
        rows.append(row)
    return rows


def _builtin_app_seed_rows() -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    rows = []
    for pkg, info in APP_REGISTRY.items():
        rows.append(
            {
                "pkg": pkg,
                "name": info["name"],
                "category": info.get("category", "general"),
                "is_builtin": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    return rows


class TaskRecommendationEngine:
    """Intelligent recommendation engine matching device capabilities."""

    def __init__(
        self,
        repository: TaskPresetRepository | None = None,
        app_repository: AppRepository | None = None,
    ):
        self.repository = repository or task_preset_repository
        self.app_repository = app_repository or default_app_repository
        self._seeded = False
        self._apps_seeded = False

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        self.repository.seed_if_empty(_builtin_seed_rows())
        self._seeded = True

    def _ensure_apps_seeded(self) -> None:
        if self._apps_seeded:
            return
        self.app_repository.seed_if_empty(_builtin_app_seed_rows())
        self._apps_seeded = True

    def get_all_tasks(self) -> list[dict[str, Any]]:
        self._ensure_seeded()
        return self.repository.list_all()

    def get_app_registry(self) -> dict[str, dict[str, str]]:
        self._ensure_apps_seeded()
        return {
            row["pkg"]: {
                "name": row["name"],
                "category": row["category"],
            }
            for row in self.app_repository.list_all()
        }

    def get_apps(self) -> list[dict[str, Any]]:
        self._ensure_apps_seeded()
        return self.app_repository.list_all()

    def recommend_tasks(
        self, installed_packages: list[str] | set[str], category: str = "all", limit: int = 12
    ) -> list[dict[str, Any]]:
        self._ensure_seeded()
        pkgs_set = (
            set(installed_packages) if isinstance(installed_packages, list) else installed_packages
        ) or set()

        scored_tasks: list[tuple[int, dict[str, Any], bool]] = []

        for row in self.repository.list_all():
            required_packages = row["required_packages"]
            is_matched = False
            if pkgs_set:
                if not required_packages:
                    is_matched = True
                elif row["match_mode"] == "all":
                    is_matched = all(pkg in pkgs_set for pkg in required_packages)
                else:
                    is_matched = any(pkg in pkgs_set for pkg in required_packages)

            score = row["priority"]
            if pkgs_set:
                if is_matched:
                    score += 100
                    if len(required_packages) > 1 and row["match_mode"] == "all":
                        score += 30
                else:
                    score -= 40

            if category == "flash" and row["profile"] != "flash":
                continue
            elif category == "pro" and row["profile"] != "pro":
                continue
            elif category == "cross_app" and row["category"] != "cross_app":
                continue
            elif category == "monitor" and row["category"] != "monitor":
                continue

            scored_tasks.append((score, row, is_matched))

        scored_tasks.sort(key=lambda item: item[0], reverse=True)

        results: list[dict[str, Any]] = []
        for _, row, matched in scored_tasks[:limit]:
            d = dict(row)
            d["is_device_matched"] = matched
            results.append(d)

        return results

    def _resolve_apps(self, app_pkgs: list[str]) -> list[AppInfo]:
        self._ensure_apps_seeded()
        apps = []
        for pkg in app_pkgs:
            row = self.app_repository.get(pkg)
            if not row:
                raise ValueError(f"Unknown app package: {pkg}")
            apps.append(AppInfo(name=row["name"], pkg=pkg, category=row.get("category", "general")))
        return apps

    def _derive_app_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compute the fields that legitimately change whenever the app
        selection (or title/description/goal/profile) changes.

        These are always safe to recompute from the submitted payload, for
        both new presets (create_task) and edits to existing ones
        (update_task).
        """
        app_pkgs = payload["app_pkgs"]
        if not app_pkgs:
            raise ValueError("At least one app must be selected.")
        apps = self._resolve_apps(app_pkgs)
        profile = payload["profile"]
        tag = " + ".join(a.name for a in apps)
        return {
            "title": payload["title"],
            "description": payload["description"],
            "goal": payload["goal"],
            "profile": profile,
            "tag": tag,
            "apps": [a.model_dump() for a in apps],
            "required_packages": app_pkgs,
        }

    def _derive_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Full field set for a BRAND NEW preset (create_task only).

        In addition to the always-recomputed app fields, this derives
        `category`, `match_mode`, and `priority` from scratch, which is the
        correct behavior for a preset that doesn't exist yet. Editing an
        existing preset must NOT go through this recomputation -- see
        update_task, which only recomputes the app fields and leaves the
        existing row's category/match_mode/priority untouched.
        """
        fields = self._derive_app_fields(payload)
        app_pkgs = payload["app_pkgs"]
        category = "cross_app" if len(app_pkgs) > 1 else fields["profile"]
        fields.update(
            {
                "category": category,
                "match_mode": "any",
                "priority": 60,
            }
        )
        return fields

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_seeded()
        fields = self._derive_fields(payload)
        now = datetime.now(UTC).isoformat()
        row = {
            "id": str(uuid.uuid4()),
            **fields,
            "is_builtin": False,
            "created_at": now,
            "updated_at": now,
        }
        return self.repository.create(row)

    def update_task(self, preset_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_seeded()
        # Only recompute the fields that legitimately change when the app
        # selection/title/description/goal/profile are edited. Deliberately
        # do NOT recompute category/match_mode/priority here (unlike
        # create_task): those are curated per-preset (e.g. "all packages
        # required" semantics, a hand-tuned priority, a specific catalog
        # tab). Omitting them from `fields` means
        # TaskPresetRepository.update() leaves those columns untouched in
        # the database, so an edit -- even one that changes the app
        # selection -- preserves the existing row's category, match_mode,
        # and priority instead of silently resetting them.
        fields = self._derive_app_fields(payload)
        fields["updated_at"] = datetime.now(UTC).isoformat()
        return self.repository.update(preset_id, fields)

    def delete_task(self, preset_id: str) -> bool:
        self._ensure_seeded()
        return self.repository.delete(preset_id)

    def create_app(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_apps_seeded()
        now = datetime.now(UTC).isoformat()
        row = {
            "pkg": payload["pkg"],
            "name": payload["name"],
            "category": payload.get("category") or "general",
            "is_builtin": False,
            "created_at": now,
            "updated_at": now,
        }
        return self.app_repository.create(row)

    def update_app(self, pkg: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_apps_seeded()
        fields = {
            "name": payload["name"],
            "category": payload.get("category") or "general",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return self.app_repository.update(pkg, fields)

    def delete_app(self, pkg: str) -> tuple[bool, int]:
        """Delete an app unless a task preset still references it.

        Returns (deleted, blocking_count). blocking_count > 0 means the
        delete was refused because that many task presets still list this
        pkg in their required_packages.
        """
        self._ensure_seeded()
        referencing = [row for row in self.repository.list_all() if pkg in row["required_packages"]]
        if referencing:
            return False, len(referencing)
        return self.app_repository.delete(pkg), 0


task_recommendation_engine = TaskRecommendationEngine()
