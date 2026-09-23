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

import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TaskRecommendationService } from '../../core/services/task-recommendation.service';
import { Schedule, ScheduleWritePayload } from '../../core/services/schedule.service';

@Component({
  selector: 'app-schedule-form',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './schedule-form.component.html',
  styleUrl: './schedule-form.component.scss'
})
export class ScheduleFormComponent implements OnChanges {
  @Input() editingSchedule: Schedule | null = null;
  @Input() errorText: string | null = null;
  @Output() save = new EventEmitter<ScheduleWritePayload>();
  @Output() cancel = new EventEmitter<void>();

  public taskRecService = inject(TaskRecommendationService);

  public presetId = signal<string>('');
  public scheduleType = signal<'once' | 'cron'>('cron');
  public runAt = signal<string>('');
  public cronExpression = signal<string>('');

  ngOnChanges(changes: SimpleChanges): void {
    // Only (re-)derive the form when the schedule being edited actually
    // changed. Without this guard, a failed save -- which flows back in as
    // a new [errorText] binding -- would reset every field and wipe what
    // the user typed. Angular includes every bound @Input in a component's
    // very first SimpleChanges, and SchedulesComponent recreates this
    // component on each modal open (@if (showModal())), so both the
    // create and edit paths still initialize correctly on open.
    if (!changes['editingSchedule']) {
      return;
    }
    const schedule = this.editingSchedule;
    const tasks = this.taskRecService.allTasks();
    this.presetId.set(schedule?.presetId ?? tasks[0]?.id ?? '');
    this.scheduleType.set(schedule?.scheduleType ?? 'cron');
    this.runAt.set(schedule?.runAt ?? '');
    this.cronExpression.set(schedule?.cronExpression ?? '');
  }

  public get isValid(): boolean {
    if (!this.presetId()) {
      return false;
    }
    return this.scheduleType() === 'once'
      ? this.runAt().trim().length > 0
      : this.cronExpression().trim().length > 0;
  }

  public onSave(): void {
    if (!this.isValid) {
      return;
    }
    this.save.emit({
      preset_id: this.presetId(),
      schedule_type: this.scheduleType(),
      run_at: this.scheduleType() === 'once' ? this.runAt() : null,
      cron_expression: this.scheduleType() === 'cron' ? this.cronExpression().trim() : null
    });
  }

  public onCancel(): void {
    this.cancel.emit();
  }
}
