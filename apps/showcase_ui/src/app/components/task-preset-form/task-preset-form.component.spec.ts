import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SmartSuggestion } from '../../core/data/smart-tasks.data';
import { TaskPresetFormComponent } from './task-preset-form.component';

describe('TaskPresetFormComponent', () => {
  let fixture: ComponentFixture<TaskPresetFormComponent>;
  let component: TaskPresetFormComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TaskPresetFormComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(TaskPresetFormComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    // TaskRecommendationService (injected for appRegistry) eagerly loads its catalog.
    http.expectOne('/api/tasks/catalog').flush({ tasks: [] });
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
      apps: [{ name: 'Maps', icon: 'explore', pkg: 'com.google.android.apps.maps' }],
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
});
