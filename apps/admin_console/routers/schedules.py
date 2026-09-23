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

"""REST endpoints for Task Scheduler CRUD."""

from fastapi import APIRouter, HTTPException

try:
    from admin_console.schemas.task_schema import ScheduleWrite
    from admin_console.services.task_scheduler_service import task_scheduler_service
except ImportError:
    from apps.admin_console.schemas.task_schema import ScheduleWrite
    from apps.admin_console.services.task_scheduler_service import task_scheduler_service


router = APIRouter(tags=["schedules"])


@router.get("/api/schedules")
async def list_schedules():
    """List all Task Scheduler schedules."""
    return task_scheduler_service.list_schedules()


@router.post("/api/schedules")
async def create_schedule(request: ScheduleWrite):
    """Create a new schedule for an existing task preset."""
    try:
        result = task_scheduler_service.create_schedule(
            request.preset_id,
            request.schedule_type,
            run_at=request.run_at,
            cron_expression=request.cron_expression,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Task preset '{request.preset_id}' not found.")
    return result


@router.put("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, request: ScheduleWrite):
    """Update an existing schedule's preset and/or trigger."""
    try:
        result = task_scheduler_service.update_schedule(
            schedule_id,
            request.preset_id,
            request.schedule_type,
            run_at=request.run_at,
            cron_expression=request.cron_expression,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Schedule '{schedule_id}' or task preset '{request.preset_id}' not found.",
        )
    return result


@router.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    if not task_scheduler_service.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found.")
    return {"status": "deleted", "id": schedule_id}


@router.post("/api/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str):
    """Pause a recurring ('cron') schedule."""
    try:
        result = task_scheduler_service.pause_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found.")
    return result


@router.post("/api/schedules/{schedule_id}/resume")
async def resume_schedule(schedule_id: str):
    """Resume a paused recurring ('cron') schedule."""
    try:
        result = task_scheduler_service.resume_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found.")
    return result
