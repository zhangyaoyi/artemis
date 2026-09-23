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
import { AppReference, SmartSuggestion } from '../../core/data/smart-tasks.data';
import { AppRegistryService, AppUpdatePayload, AppWritePayload } from '../../core/services/app-registry.service';
import { TaskPresetWritePayload } from '../../core/services/task-recommendation.service';

@Component({
  selector: 'app-task-preset-form',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './task-preset-form.component.html',
  styleUrl: './task-preset-form.component.scss'
})
export class TaskPresetFormComponent implements OnChanges {
  @Input() editingTask: SmartSuggestion | null = null;
  @Input() errorText: string | null = null;
  @Output() save = new EventEmitter<TaskPresetWritePayload>();
  @Output() cancel = new EventEmitter<void>();

  public appRegistryService = inject(AppRegistryService);

  public title = signal<string>('');
  public description = signal<string>('');
  public goal = signal<string>('');
  public profile = signal<'flash' | 'pro'>('flash');
  public selectedPkgs = signal<Set<string>>(new Set());

  // Inline app-registry management (add/edit/delete an app from within
  // this modal's app picker).
  public showAppForm = signal<boolean>(false);
  public editingApp = signal<AppReference | null>(null);
  public appFormPkg = signal<string>('');
  public appFormName = signal<string>('');
  public appFormCategory = signal<string>('general');
  public appFormError = signal<string | null>(null);
  public appDeleteError = signal<string | null>(null);

  ngOnChanges(_changes: SimpleChanges): void {
    const task = this.editingTask;
    this.title.set(task?.title ?? '');
    this.description.set(task?.description ?? '');
    this.goal.set(task?.goal ?? '');
    this.profile.set(task?.profile ?? 'flash');
    this.selectedPkgs.set(new Set(task?.requiredPackages ?? []));
  }

  public isPkgSelected(pkg: string): boolean {
    return this.selectedPkgs().has(pkg);
  }

  public togglePkg(pkg: string): void {
    const next = new Set(this.selectedPkgs());
    if (next.has(pkg)) {
      next.delete(pkg);
    } else {
      next.add(pkg);
    }
    this.selectedPkgs.set(next);
  }

  public get isValid(): boolean {
    return (
      this.title().trim().length > 0 &&
      this.description().trim().length > 0 &&
      this.goal().trim().length > 0 &&
      this.selectedPkgs().size > 0
    );
  }

  public onSave(): void {
    if (!this.isValid) {
      return;
    }
    this.save.emit({
      title: this.title().trim(),
      description: this.description().trim(),
      goal: this.goal().trim(),
      profile: this.profile(),
      app_pkgs: Array.from(this.selectedPkgs())
    });
  }

  public onCancel(): void {
    this.cancel.emit();
  }

  // --- Inline app-registry management ---

  public openAddAppForm(): void {
    this.editingApp.set(null);
    this.appFormPkg.set('');
    this.appFormName.set('');
    this.appFormCategory.set('general');
    this.appFormError.set(null);
    this.showAppForm.set(true);
  }

  public openEditAppForm(app: AppReference, event: Event): void {
    event.stopPropagation();
    this.editingApp.set(app);
    this.appFormPkg.set(app.pkg ?? '');
    this.appFormName.set(app.name);
    this.appFormCategory.set(app.category ?? 'general');
    this.appFormError.set(null);
    this.showAppForm.set(true);
  }

  public closeAppForm(): void {
    this.showAppForm.set(false);
    this.editingApp.set(null);
    this.appFormError.set(null);
  }

  public get isAppFormValid(): boolean {
    const pkgOk = this.editingApp() !== null || this.appFormPkg().trim().length > 0;
    return pkgOk && this.appFormName().trim().length > 0;
  }

  public saveApp(): void {
    if (!this.isAppFormValid) {
      return;
    }
    const editing = this.editingApp();
    const updatePayload: AppUpdatePayload = {
      name: this.appFormName().trim(),
      category: this.appFormCategory().trim() || 'general'
    };
    const request$ = editing
      ? this.appRegistryService.updateApp(editing.pkg!, updatePayload)
      : this.appRegistryService.createApp({
          pkg: this.appFormPkg().trim(),
          ...updatePayload
        } as AppWritePayload);
    request$.subscribe({
      next: () => this.closeAppForm(),
      error: (err) => this.appFormError.set(err?.error?.detail || 'Failed to save app.')
    });
  }

  public deleteApp(app: AppReference, event: Event): void {
    event.stopPropagation();
    if (!app.pkg) {
      return;
    }
    this.appDeleteError.set(null);
    this.appRegistryService.deleteApp(app.pkg).subscribe({
      error: (err) => this.appDeleteError.set(err?.error?.detail || 'Failed to delete app.')
    });
  }
}
