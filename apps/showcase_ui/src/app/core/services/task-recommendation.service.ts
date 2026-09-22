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

import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, tap } from 'rxjs';
import {
  AppReference,
  SmartSuggestion,
  SuggestionCategory,
  APP_REGISTRY
} from '../data/smart-tasks.data';

export interface TaskPresetWritePayload {
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  app_pkgs: string[];
}

interface RawTaskPreset {
  id: string;
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  category: 'flash' | 'pro' | 'cross_app' | 'monitor';
  tag: string;
  apps: AppReference[];
  required_packages: string[];
  match_mode: 'any' | 'all';
  priority: number;
  is_builtin: boolean;
}

function mapPreset(raw: RawTaskPreset): SmartSuggestion {
  return {
    id: raw.id,
    title: raw.title,
    description: raw.description,
    goal: raw.goal,
    profile: raw.profile,
    category: raw.category,
    tag: raw.tag,
    apps: raw.apps,
    requiredPackages: raw.required_packages,
    matchMode: raw.match_mode,
    priority: raw.priority,
    isBuiltin: raw.is_builtin
  };
}

@Injectable({
  providedIn: 'root'
})
export class TaskRecommendationService {
  private http = inject(HttpClient);

  public readonly appRegistry = APP_REGISTRY;
  public allTasks = signal<SmartSuggestion[]>([]);

  constructor() {
    this.loadTasks().subscribe();
  }

  /**
   * Fetches the full task preset catalog from the backend and replaces
   * `allTasks`. Called on service init and after every mutation.
   */
  public loadTasks(): Observable<{ tasks: RawTaskPreset[] }> {
    return this.http.get<{ tasks: RawTaskPreset[] }>('/api/tasks/catalog').pipe(
      tap({
        next: (response) => this.allTasks.set(response.tasks.map(mapPreset)),
        error: (err) => console.error('Failed to load task presets:', err)
      })
    );
  }

  public createTask(payload: TaskPresetWritePayload): Observable<SmartSuggestion> {
    return this.http.post<RawTaskPreset>('/api/tasks/presets', payload).pipe(
      tap(() => this.loadTasks().subscribe()),
      map((raw) => mapPreset(raw))
    );
  }

  public updateTask(id: string, payload: TaskPresetWritePayload): Observable<SmartSuggestion> {
    return this.http.put<RawTaskPreset>(`/api/tasks/presets/${id}`, payload).pipe(
      tap(() => this.loadTasks().subscribe()),
      map((raw) => mapPreset(raw))
    );
  }

  public deleteTask(id: string): Observable<{ status: string; id: string }> {
    return this.http.delete<{ status: string; id: string }>(`/api/tasks/presets/${id}`).pipe(
      tap({
        next: () => this.loadTasks().subscribe()
      })
    );
  }

  /**
   * Check if task matches any package installed on device
   */
  public isSuggestionOnDevice(
    suggestion: SmartSuggestion,
    installedPackages: Set<string>
  ): boolean {
    if (installedPackages.size === 0) return false;
    if (!suggestion.requiredPackages || suggestion.requiredPackages.length === 0) {
      return true;
    }

    if (suggestion.matchMode === 'all') {
      return suggestion.requiredPackages.every(pkg => installedPackages.has(pkg));
    }
    return suggestion.requiredPackages.some(pkg => installedPackages.has(pkg));
  }

  /**
   * Intelligently rank and filter tasks:
   * Prioritizes tasks matching apps detected on user's phone without exposing clutter.
   */
  public filterAndRankTasks(
    installedPackages: Set<string>,
    category: SuggestionCategory,
    shuffleOffset: number = 0
  ): SmartSuggestion[] {
    const hasDevice = installedPackages.size > 0;

    // 1. Score tasks: prioritize tasks whose apps are on the user's phone
    const scored = this.allTasks().map(task => {
      const isMatched = this.isSuggestionOnDevice(task, installedPackages);
      let score = task.priority ?? 50;

      if (hasDevice) {
        if (isMatched) {
          score += 100;
          if (task.requiredPackages && task.requiredPackages.length > 1 && task.matchMode === 'all') {
            score += 30; // bonus for full multi-app synergy match
          }
        } else {
          score -= 40;
        }
      }

      return { task, isMatched, score };
    });

    // 2. Filter by category
    let filtered = scored.filter(item => {
      if (category === 'flash') {
        return item.task.profile === 'flash';
      }
      if (category === 'pro') {
        return item.task.profile === 'pro';
      }
      if (category === 'cross_app') {
        return item.task.category === 'cross_app';
      }
      if (category === 'monitor') {
        return item.task.category === 'monitor';
      }
      return true; // 'all'
    });

    // 3. Sort by score descending (matched apps first)
    filtered.sort((a, b) => b.score - a.score);

    let result = filtered.map(f => f.task);

    // 4. Apply shuffle rotation
    if (shuffleOffset > 0 && result.length > 0) {
      const shift = shuffleOffset % result.length;
      result = [...result.slice(shift), ...result.slice(0, shift)];
    }

    return result;
  }
}
