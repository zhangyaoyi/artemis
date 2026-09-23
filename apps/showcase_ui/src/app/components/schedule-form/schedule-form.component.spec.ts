import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Schedule } from '../../core/services/schedule.service';
import { ScheduleFormComponent } from './schedule-form.component';

describe('ScheduleFormComponent', () => {
  let fixture: ComponentFixture<ScheduleFormComponent>;
  let component: ScheduleFormComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ScheduleFormComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(ScheduleFormComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    // TaskRecommendationService (injected for the preset dropdown) eagerly loads its catalog.
    http.expectOne('/api/tasks/catalog').flush({
      tasks: [
        {
          id: 'preset-1',
          title: 'Clear Cache',
          description: 'd',
          goal: 'g',
          profile: 'flash',
          category: 'flash',
          tag: 'Test',
          apps: [],
          required_packages: [],
          match_mode: 'any',
          priority: 60,
          is_builtin: false
        }
      ]
    });
  });

  afterEach(() => http.verify());

  it('defaults to the first preset and cron type in create mode', () => {
    component.ngOnChanges({ editingSchedule: {} as never });

    expect(component.presetId()).toBe('preset-1');
    expect(component.scheduleType()).toBe('cron');
    expect(component.isValid).toBeFalse();
  });

  it('pre-fills fields when editing an existing schedule', () => {
    const schedule: Schedule = {
      id: 'sched_1',
      presetId: 'preset-1',
      presetTitle: 'Clear Cache',
      scheduleType: 'once',
      runAt: '2026-09-25T09:00',
      cronExpression: null,
      nextRunTime: '2026-09-25T09:00:00',
      paused: false,
      lastRunAt: null,
      lastStatus: null
    };
    component.editingSchedule = schedule;

    component.ngOnChanges({ editingSchedule: {} as never });

    expect(component.presetId()).toBe('preset-1');
    expect(component.scheduleType()).toBe('once');
    expect(component.runAt()).toBe('2026-09-25T09:00');
  });

  it('requires a cron expression when schedule type is cron', () => {
    component.ngOnChanges({ editingSchedule: {} as never });

    expect(component.isValid).toBeFalse();

    component.cronExpression.set('0 9 * * *');

    expect(component.isValid).toBeTrue();
  });

  it('requires a run-at datetime when schedule type is once', () => {
    component.ngOnChanges({ editingSchedule: {} as never });
    component.scheduleType.set('once');

    expect(component.isValid).toBeFalse();

    component.runAt.set('2026-09-25T09:00');

    expect(component.isValid).toBeTrue();
  });

  it('emits save with a cron payload', () => {
    component.ngOnChanges({ editingSchedule: {} as never });
    component.cronExpression.set('0 9 * * 1,3,5');

    let emitted: unknown = null;
    component.save.subscribe(v => (emitted = v));
    component.onSave();

    expect(emitted).toEqual({
      preset_id: 'preset-1',
      schedule_type: 'cron',
      run_at: null,
      cron_expression: '0 9 * * 1,3,5'
    });
  });

  it('emits save with a once payload', () => {
    component.ngOnChanges({ editingSchedule: {} as never });
    component.scheduleType.set('once');
    component.runAt.set('2026-09-25T09:00');

    let emitted: unknown = null;
    component.save.subscribe(v => (emitted = v));
    component.onSave();

    expect(emitted).toEqual({
      preset_id: 'preset-1',
      schedule_type: 'once',
      run_at: '2026-09-25T09:00',
      cron_expression: null
    });
  });

  it('keeps user input when only errorText changes (failed save)', () => {
    component.ngOnChanges({ editingSchedule: {} as never });
    component.scheduleType.set('once');
    component.runAt.set('2026-09-25T09:00');

    // What a failed save looks like: SchedulesComponent sets modalError,
    // which is bound to [errorText] -- editingSchedule is untouched.
    component.errorText = 'run_at must be in the future.';
    component.ngOnChanges({ errorText: {} as never });

    expect(component.scheduleType()).toBe('once');
    expect(component.runAt()).toBe('2026-09-25T09:00');
    expect(component.isValid).toBeTrue();
  });

  it('emits cancel', () => {
    let called = false;
    component.cancel.subscribe(() => (called = true));
    component.onCancel();
    expect(called).toBeTrue();
  });
});
