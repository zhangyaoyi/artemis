import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { TaskRecommendationService } from './task-recommendation.service';

describe('TaskRecommendationService', () => {
  let service: TaskRecommendationService;
  let http: HttpTestingController;

  const rawTask = (overrides: Record<string, unknown> = {}) => ({
    id: 'task-1',
    title: 'Find Coffee',
    description: 'desc',
    goal: 'goal',
    profile: 'flash',
    category: 'flash',
    tag: 'Maps',
    apps: [
      { name: 'Maps', icon: 'explore', pkg: 'com.google.android.apps.maps', category: 'navigation' }
    ],
    required_packages: ['com.google.android.apps.maps'],
    match_mode: 'any',
    priority: 95,
    is_builtin: true,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        TaskRecommendationService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(TaskRecommendationService);
    http = TestBed.inject(HttpTestingController);
    // The constructor eagerly loads the catalog; drain that request first.
    http.expectOne('/api/tasks/catalog').flush({ tasks: [] });
  });

  afterEach(() => http.verify());

  it('maps snake_case API fields to camelCase SmartSuggestion fields', () => {
    service.loadTasks().subscribe();
    const req = http.expectOne('/api/tasks/catalog');
    req.flush({ tasks: [rawTask()] });

    const loaded = service.allTasks();
    expect(loaded.length).toBe(1);
    expect(loaded[0].requiredPackages).toEqual(['com.google.android.apps.maps']);
    expect(loaded[0].matchMode).toBe('any');
    expect(loaded[0].isBuiltin).toBe(true);
  });

  it('creates a task then refreshes the list', () => {
    service.createTask({
      title: 'New',
      description: 'd',
      goal: 'g',
      profile: 'flash',
      app_pkgs: ['com.android.chrome']
    }).subscribe();

    const createReq = http.expectOne('/api/tasks/presets');
    expect(createReq.request.method).toBe('POST');
    createReq.flush(rawTask({ id: 'task-2' }));

    const refreshReq = http.expectOne('/api/tasks/catalog');
    refreshReq.flush({ tasks: [rawTask({ id: 'task-2' })] });

    expect(service.allTasks().map(t => t.id)).toEqual(['task-2']);
  });

  it('updates a task by id then refreshes the list', () => {
    service.updateTask('task-1', {
      title: 'Renamed',
      description: 'd',
      goal: 'g',
      profile: 'flash',
      app_pkgs: ['com.android.chrome']
    }).subscribe();

    const updateReq = http.expectOne('/api/tasks/presets/task-1');
    expect(updateReq.request.method).toBe('PUT');
    updateReq.flush(rawTask({ title: 'Renamed' }));

    const refreshReq = http.expectOne('/api/tasks/catalog');
    refreshReq.flush({ tasks: [rawTask({ title: 'Renamed' })] });

    expect(service.allTasks()[0].title).toBe('Renamed');
  });

  it('deletes a task by id then refreshes the list', () => {
    service.deleteTask('task-1').subscribe();

    const deleteReq = http.expectOne('/api/tasks/presets/task-1');
    expect(deleteReq.request.method).toBe('DELETE');
    deleteReq.flush({ status: 'deleted', id: 'task-1' });

    const refreshReq = http.expectOne('/api/tasks/catalog');
    refreshReq.flush({ tasks: [] });

    expect(service.allTasks()).toEqual([]);
  });
});
