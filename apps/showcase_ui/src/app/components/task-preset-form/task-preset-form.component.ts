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
import { TaskPresetWritePayload, TaskRecommendationService } from '../../core/services/task-recommendation.service';

@Component({
  selector: 'app-task-preset-form',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './task-preset-form.component.html',
  styleUrl: './task-preset-form.component.scss'
})
export class TaskPresetFormComponent implements OnChanges {
  @Input() editingTask: SmartSuggestion | null = null;
  @Output() save = new EventEmitter<TaskPresetWritePayload>();
  @Output() cancel = new EventEmitter<void>();

  private taskRecService = inject(TaskRecommendationService);
  public appRegistryEntries: Array<[string, AppReference]> = Object.entries(this.taskRecService.appRegistry);

  public title = signal<string>('');
  public description = signal<string>('');
  public goal = signal<string>('');
  public profile = signal<'flash' | 'pro'>('flash');
  public selectedPkgs = signal<Set<string>>(new Set());

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
}
