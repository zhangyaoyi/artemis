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

import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Schedule, ScheduleService, ScheduleWritePayload } from '../../core/services/schedule.service';
import { ScheduleFormComponent } from '../../components/schedule-form/schedule-form.component';

@Component({
  selector: 'app-schedules',
  standalone: true,
  imports: [ScheduleFormComponent, DatePipe],
  templateUrl: './schedules.component.html',
  styleUrl: './schedules.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SchedulesComponent {
  public scheduleService = inject(ScheduleService);

  public showModal = signal<boolean>(false);
  public editingSchedule = signal<Schedule | null>(null);
  public modalError = signal<string | null>(null);
  public errorMessage = signal<string | null>(null);

  public openAddModal(): void {
    this.editingSchedule.set(null);
    this.modalError.set(null);
    this.showModal.set(true);
  }

  public openEditModal(schedule: Schedule): void {
    this.editingSchedule.set(schedule);
    this.modalError.set(null);
    this.showModal.set(true);
  }

  public closeModal(): void {
    this.showModal.set(false);
    this.editingSchedule.set(null);
    this.modalError.set(null);
  }

  public saveSchedule(payload: ScheduleWritePayload): void {
    const editing = this.editingSchedule();
    const request$ = editing
      ? this.scheduleService.updateSchedule(editing.id, payload)
      : this.scheduleService.createSchedule(payload);
    request$.subscribe({
      next: () => this.closeModal(),
      error: (err) => {
        const message = err?.error?.detail || 'Failed to save schedule.';
        this.errorMessage.set(message);
        this.modalError.set(message);
        this.scheduleService.loadSchedules().subscribe();
      }
    });
  }

  public deleteSchedule(schedule: Schedule): void {
    if (!confirm(`Delete the schedule for "${schedule.presetTitle}"?`)) {
      return;
    }
    this.scheduleService.deleteSchedule(schedule.id).subscribe({
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to delete schedule.');
        this.scheduleService.loadSchedules().subscribe();
      }
    });
  }

  public togglePause(schedule: Schedule): void {
    const request$ = schedule.paused
      ? this.scheduleService.resumeSchedule(schedule.id)
      : this.scheduleService.pauseSchedule(schedule.id);
    request$.subscribe({
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to update schedule.');
        this.scheduleService.loadSchedules().subscribe();
      }
    });
  }
}
