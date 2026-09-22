import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AppRegistryService } from './app-registry.service';

describe('AppRegistryService', () => {
  let service: AppRegistryService;
  let http: HttpTestingController;

  const rawApp = (overrides: Record<string, unknown> = {}) => ({
    pkg: 'com.android.chrome',
    name: 'Chrome',
    icon: 'public',
    category: 'browser',
    is_builtin: true,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AppRegistryService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(AppRegistryService);
    http = TestBed.inject(HttpTestingController);
    // The constructor eagerly loads the registry; drain that request first.
    http.expectOne('/api/apps').flush([]);
  });

  afterEach(() => http.verify());

  it('maps snake_case API fields to camelCase AppReference fields', () => {
    service.loadApps().subscribe();
    const req = http.expectOne('/api/apps');
    req.flush([rawApp()]);

    const loaded = service.apps();
    expect(loaded.length).toBe(1);
    expect(loaded[0].pkg).toBe('com.android.chrome');
    expect(loaded[0].isBuiltin).toBe(true);
  });

  it('creates an app then refreshes the list', () => {
    service.createApp({
      pkg: 'com.example.newapp',
      name: 'New App',
      icon: 'star',
      category: 'tools'
    }).subscribe();

    const createReq = http.expectOne('/api/apps');
    expect(createReq.request.method).toBe('POST');
    createReq.flush(rawApp({ pkg: 'com.example.newapp', name: 'New App' }));

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([rawApp({ pkg: 'com.example.newapp', name: 'New App' })]);

    expect(service.apps().map(a => a.pkg)).toEqual(['com.example.newapp']);
  });

  it('updates an app by pkg then refreshes the list', () => {
    service.updateApp('com.android.chrome', {
      name: 'Renamed',
      icon: 'public',
      category: 'browser'
    }).subscribe();

    const updateReq = http.expectOne('/api/apps/com.android.chrome');
    expect(updateReq.request.method).toBe('PUT');
    updateReq.flush(rawApp({ name: 'Renamed' }));

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([rawApp({ name: 'Renamed' })]);

    expect(service.apps()[0].name).toBe('Renamed');
  });

  it('deletes an app by pkg then refreshes the list', () => {
    service.deleteApp('com.android.chrome').subscribe();

    const deleteReq = http.expectOne('/api/apps/com.android.chrome');
    expect(deleteReq.request.method).toBe('DELETE');
    deleteReq.flush({ status: 'deleted', pkg: 'com.android.chrome' });

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([]);

    expect(service.apps()).toEqual([]);
  });
});
