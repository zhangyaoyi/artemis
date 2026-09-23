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

type SimpleScheduleFrequency =
  | 'daily'
  | 'weekdays'
  | 'weekends'
  | 'weekly'
  | 'monthly'
  | 'custom';

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
  public simpleFrequency = signal<SimpleScheduleFrequency>('daily');
  public simpleTime = signal<string>('09:00');
  public simpleWeekday = signal<string>('0');
  public simpleMonthDay = signal<number>(1);

  public readonly weekdays = [
    { value: '0', label: 'Monday' },
    { value: '1', label: 'Tuesday' },
    { value: '2', label: 'Wednesday' },
    { value: '3', label: 'Thursday' },
    { value: '4', label: 'Friday' },
    { value: '5', label: 'Saturday' },
    { value: '6', label: 'Sunday' }
  ];

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
    const cronExpression = schedule?.cronExpression ?? '';
    if (cronExpression) {
      this.onCronExpressionChange(cronExpression);
    } else {
      this.simpleFrequency.set('daily');
      this.simpleTime.set('09:00');
      this.simpleWeekday.set('0');
      this.simpleMonthDay.set(1);
      this.updateCronFromSimpleSchedule();
    }
  }

  public setSimpleFrequency(value: string): void {
    const supported: SimpleScheduleFrequency[] = [
      'daily', 'weekdays', 'weekends', 'weekly', 'monthly', 'custom'
    ];
    if (!supported.includes(value as SimpleScheduleFrequency)) {
      return;
    }
    this.simpleFrequency.set(value as SimpleScheduleFrequency);
    if (value !== 'custom') {
      this.updateCronFromSimpleSchedule();
    }
  }

  public setSimpleTime(value: string): void {
    this.simpleTime.set(value);
    this.updateCronFromSimpleSchedule();
  }

  public setSimpleWeekday(value: string): void {
    this.simpleWeekday.set(value);
    this.updateCronFromSimpleSchedule();
  }

  public setSimpleMonthDay(value: number | string): void {
    const day = Math.min(31, Math.max(1, Number(value) || 1));
    this.simpleMonthDay.set(day);
    this.updateCronFromSimpleSchedule();
  }

  public onCronExpressionChange(value: string): void {
    this.cronExpression.set(value);
    this.populateSimpleSchedule(value);
  }

  private updateCronFromSimpleSchedule(): void {
    const match = /^(\d{2}):(\d{2})$/.exec(this.simpleTime());
    if (!match || this.simpleFrequency() === 'custom') {
      return;
    }
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour > 23 || minute > 59) {
      return;
    }

    let day = '*';
    let weekday = '*';
    switch (this.simpleFrequency()) {
      case 'weekdays':
        weekday = '0-4';
        break;
      case 'weekends':
        weekday = '5,6';
        break;
      case 'weekly':
        weekday = this.simpleWeekday();
        break;
      case 'monthly':
        day = String(this.simpleMonthDay());
        break;
    }
    this.cronExpression.set(`${minute} ${hour} ${day} * ${weekday}`);
  }

  private populateSimpleSchedule(expression: string): void {
    const fields = expression.trim().split(/\s+/);
    if (fields.length !== 5) {
      this.simpleFrequency.set('custom');
      return;
    }
    const [minuteField, hourField, day, month, weekday] = fields;
    const minute = Number(minuteField);
    const hour = Number(hourField);
    if (
      !/^\d+$/.test(minuteField) || !/^\d+$/.test(hourField) ||
      minute > 59 || hour > 23 || month !== '*'
    ) {
      this.simpleFrequency.set('custom');
      return;
    }
    this.simpleTime.set(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);

    if (day === '*' && weekday === '*') {
      this.simpleFrequency.set('daily');
    } else if (day === '*' && weekday === '0-4') {
      this.simpleFrequency.set('weekdays');
    } else if (day === '*' && weekday === '5,6') {
      this.simpleFrequency.set('weekends');
    } else if (day === '*' && /^[0-6]$/.test(weekday)) {
      this.simpleFrequency.set('weekly');
      this.simpleWeekday.set(weekday);
    } else if (/^(?:[1-9]|[12]\d|3[01])$/.test(day) && weekday === '*') {
      this.simpleFrequency.set('monthly');
      this.simpleMonthDay.set(Number(day));
    } else {
      this.simpleFrequency.set('custom');
    }
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
