import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ScheduleService } from './schedule.service';

describe('ScheduleService', () => {
  let service: ScheduleService;
  let http: HttpTestingController;

  const rawSchedule = (overrides: Record<string, unknown> = {}) => ({
    id: 'sched_1',
    preset_id: 'preset-1',
    preset_title: 'Clear Cache',
    schedule_type: 'cron',
    run_at: null,
    cron_expression: '0 9 * * 1,3,5',
    next_run_time: '2026-09-24T09:00:00',
    paused: false,
    last_run_at: null,
    last_status: null,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ScheduleService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(ScheduleService);
    http = TestBed.inject(HttpTestingController);
    // The constructor eagerly loads the schedule list; drain that request first.
    http.expectOne('/api/schedules').flush([]);
  });

  afterEach(() => http.verify());

  it('maps snake_case API fields to camelCase Schedule fields', () => {
    service.loadSchedules().subscribe();
    const req = http.expectOne('/api/schedules');
    req.flush([rawSchedule()]);

    const loaded = service.schedules();
    expect(loaded.length).toBe(1);
    expect(loaded[0].presetId).toBe('preset-1');
    expect(loaded[0].cronExpression).toBe('0 9 * * 1,3,5');
  });

  it('creates a schedule then refreshes the list', () => {
    service.createSchedule({
      preset_id: 'preset-1',
      schedule_type: 'cron',
      cron_expression: '0 9 * * 1,3,5'
    }).subscribe();

    const createReq = http.expectOne('/api/schedules');
    expect(createReq.request.method).toBe('POST');
    createReq.flush(rawSchedule());

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule()]);

    expect(service.schedules().length).toBe(1);
  });

  it('updates a schedule by id then refreshes the list', () => {
    service.updateSchedule('sched_1', {
      preset_id: 'preset-1',
      schedule_type: 'cron',
      cron_expression: '0 18 * * *'
    }).subscribe();

    const updateReq = http.expectOne('/api/schedules/sched_1');
    expect(updateReq.request.method).toBe('PUT');
    updateReq.flush(rawSchedule({ cron_expression: '0 18 * * *' }));

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule({ cron_expression: '0 18 * * *' })]);

    expect(service.schedules()[0].cronExpression).toBe('0 18 * * *');
  });

  it('deletes a schedule by id then refreshes the list', () => {
    service.deleteSchedule('sched_1').subscribe();

    const deleteReq = http.expectOne('/api/schedules/sched_1');
    expect(deleteReq.request.method).toBe('DELETE');
    deleteReq.flush({ status: 'deleted', id: 'sched_1' });

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([]);

    expect(service.schedules()).toEqual([]);
  });

  it('pauses a schedule then refreshes the list', () => {
    service.pauseSchedule('sched_1').subscribe();

    const pauseReq = http.expectOne('/api/schedules/sched_1/pause');
    expect(pauseReq.request.method).toBe('POST');
    pauseReq.flush(rawSchedule({ paused: true }));

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule({ paused: true })]);

    expect(service.schedules()[0].paused).toBe(true);
  });

  it('resumes a schedule then refreshes the list', () => {
    service.resumeSchedule('sched_1').subscribe();

    const resumeReq = http.expectOne('/api/schedules/sched_1/resume');
    expect(resumeReq.request.method).toBe('POST');
    resumeReq.flush(rawSchedule({ paused: false }));

    const refreshReq = http.expectOne('/api/schedules');
    refreshReq.flush([rawSchedule({ paused: false })]);

    expect(service.schedules()[0].paused).toBe(false);
  });
});
