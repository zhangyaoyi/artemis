/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, tap } from 'rxjs';

export interface ScheduleWritePayload {
  preset_id: string;
  schedule_type: 'once' | 'cron';
  run_at?: string | null;
  cron_expression?: string | null;
}

export interface Schedule {
  id: string;
  presetId: string;
  presetTitle: string;
  scheduleType: 'once' | 'cron';
  runAt: string | null;
  cronExpression: string | null;
  nextRunTime: string | null;
  paused: boolean;
  lastRunAt: string | null;
  lastStatus: string | null;
}

interface RawSchedule {
  id: string;
  preset_id: string;
  preset_title: string;
  schedule_type: 'once' | 'cron';
  run_at: string | null;
  cron_expression: string | null;
  next_run_time: string | null;
  paused: boolean;
  last_run_at: string | null;
  last_status: string | null;
}

function mapSchedule(raw: RawSchedule): Schedule {
  return {
    id: raw.id,
    presetId: raw.preset_id,
    presetTitle: raw.preset_title,
    scheduleType: raw.schedule_type,
    runAt: raw.run_at,
    cronExpression: raw.cron_expression,
    nextRunTime: raw.next_run_time,
    paused: raw.paused,
    lastRunAt: raw.last_run_at,
    lastStatus: raw.last_status
  };
}

@Injectable({
  providedIn: 'root'
})
export class ScheduleService {
  private http = inject(HttpClient);

  public schedules = signal<Schedule[]>([]);

  constructor() {
    this.loadSchedules().subscribe();
  }

  /**
   * Fetches all schedules from the backend and replaces `schedules`.
   * Called on service init and after every mutation.
   */
  public loadSchedules(): Observable<RawSchedule[]> {
    return this.http.get<RawSchedule[]>('/api/schedules').pipe(
      tap({
        next: (response) => this.schedules.set(response.map(mapSchedule)),
        error: (err) => console.error('Failed to load schedules:', err)
      })
    );
  }

  public createSchedule(payload: ScheduleWritePayload): Observable<Schedule> {
    return this.http.post<RawSchedule>('/api/schedules', payload).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }

  public updateSchedule(id: string, payload: ScheduleWritePayload): Observable<Schedule> {
    return this.http.put<RawSchedule>(`/api/schedules/${encodeURIComponent(id)}`, payload).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }

  public deleteSchedule(id: string): Observable<{ status: string; id: string }> {
    return this.http.delete<{ status: string; id: string }>(`/api/schedules/${encodeURIComponent(id)}`).pipe(
      tap(() => this.loadSchedules().subscribe())
    );
  }

  public pauseSchedule(id: string): Observable<Schedule> {
    return this.http.post<RawSchedule>(`/api/schedules/${encodeURIComponent(id)}/pause`, {}).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }

  public resumeSchedule(id: string): Observable<Schedule> {
    return this.http.post<RawSchedule>(`/api/schedules/${encodeURIComponent(id)}/resume`, {}).pipe(
      tap(() => this.loadSchedules().subscribe()),
      map((raw) => mapSchedule(raw))
    );
  }
}
