import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AppReference, SmartSuggestion } from '../../core/data/smart-tasks.data';
import { TaskPresetFormComponent } from './task-preset-form.component';

describe('TaskPresetFormComponent', () => {
  let fixture: ComponentFixture<TaskPresetFormComponent>;
  let component: TaskPresetFormComponent;
  let http: HttpTestingController;

  const rawApp = (overrides: Record<string, unknown> = {}) => ({
    pkg: 'com.android.chrome',
    name: 'Chrome',
    category: 'browser',
    is_builtin: true,
    ...overrides
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TaskPresetFormComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(TaskPresetFormComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    // AppRegistryService (injected for the app picker) eagerly loads its list.
    http.expectOne('/api/apps').flush([rawApp()]);
  });

  afterEach(() => http.verify());

  it('starts empty in create mode', () => {
    component.ngOnChanges({} as never);

    expect(component.title()).toBe('');
    expect(component.isValid).toBeFalse();
  });

  it('pre-fills fields when editing an existing task', () => {
    const task: SmartSuggestion = {
      id: 'task-1',
      title: 'Find Coffee',
      description: 'desc',
      goal: 'goal',
      profile: 'flash',
      category: 'flash',
      tag: 'Maps',
      apps: [{ name: 'Maps', pkg: 'com.google.android.apps.maps' }],
      requiredPackages: ['com.google.android.apps.maps']
    };
    component.editingTask = task;

    component.ngOnChanges({ editingTask: {} as never });

    expect(component.title()).toBe('Find Coffee');
    expect(component.isPkgSelected('com.google.android.apps.maps')).toBeTrue();
  });

  it('requires at least one selected app to be valid', () => {
    component.ngOnChanges({} as never);
    component.title.set('T');
    component.description.set('D');
    component.goal.set('G');

    expect(component.isValid).toBeFalse();

    component.togglePkg('com.android.chrome');

    expect(component.isValid).toBeTrue();
  });

  it('emits save with the derived payload', () => {
    component.ngOnChanges({} as never);
    component.title.set('T');
    component.description.set('D');
    component.goal.set('G');
    component.togglePkg('com.android.chrome');

    let emitted: unknown = null;
    component.save.subscribe(v => (emitted = v));
    component.onSave();

    expect(emitted).toEqual({
      title: 'T',
      description: 'D',
      goal: 'G',
      profile: 'flash',
      app_pkgs: ['com.android.chrome']
    });
  });

  it('emits cancel', () => {
    let called = false;
    component.cancel.subscribe(() => (called = true));
    component.onCancel();
    expect(called).toBeTrue();
  });

  it('opens the add-app form empty and requires a pkg to be valid', () => {
    component.openAddAppForm();

    expect(component.showAppForm()).toBeTrue();
    expect(component.editingApp()).toBeNull();
    expect(component.appFormPkg()).toBe('');
    expect(component.isAppFormValid).toBeFalse();

    component.appFormPkg.set('com.example.newapp');
    component.appFormName.set('New App');

    expect(component.isAppFormValid).toBeTrue();
  });

  it('opens the edit-app form pre-filled and does not require re-entering pkg', () => {
    const app: AppReference = { name: 'Chrome', pkg: 'com.android.chrome', category: 'browser' };

    component.openEditAppForm(app, new Event('click'));

    expect(component.editingApp()).toEqual(app);
    expect(component.appFormName()).toBe('Chrome');
    expect(component.isAppFormValid).toBeTrue();
  });

  it('creates a new app via the mini-form and closes it on success', () => {
    component.openAddAppForm();
    component.appFormPkg.set('com.example.newapp');
    component.appFormName.set('New App');

    component.saveApp();

    const req = http.expectOne('/api/apps');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ pkg: 'com.example.newapp', name: 'New App', category: 'general' });
    req.flush(rawApp({ pkg: 'com.example.newapp', name: 'New App', category: 'general' }));

    const refreshReq = http.expectOne('/api/apps');
    refreshReq.flush([rawApp(), rawApp({ pkg: 'com.example.newapp', name: 'New App' })]);

    expect(component.showAppForm()).toBeFalse();
  });

  it('shows an inline error when saving an app fails', () => {
    component.openAddAppForm();
    component.appFormPkg.set('com.android.chrome');
    component.appFormName.set('Chrome Again');

    component.saveApp();

    const req = http.expectOne('/api/apps');
    req.flush({ detail: "App 'com.android.chrome' already exists." }, { status: 409, statusText: 'Conflict' });

    expect(component.appFormError()).toBe("App 'com.android.chrome' already exists.");
    expect(component.showAppForm()).toBeTrue();
  });

  it('deletes an app and shows an inline error when blocked by a referencing preset', () => {
    const app: AppReference = { name: 'Chrome', pkg: 'com.android.chrome', category: 'browser' };

    component.deleteApp(app, new Event('click'));

    const req = http.expectOne('/api/apps/com.android.chrome');
    expect(req.request.method).toBe('DELETE');
    req.flush({ detail: 'Used by 2 task preset(s).' }, { status: 409, statusText: 'Conflict' });

    expect(component.appDeleteError()).toBe('Used by 2 task preset(s).');
  });
});
