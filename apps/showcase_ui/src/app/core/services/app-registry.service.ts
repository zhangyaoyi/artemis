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
import { AppReference } from '../data/smart-tasks.data';

export interface AppWritePayload {
  pkg: string;
  name: string;
  icon: string;
  category: string;
}

export interface AppUpdatePayload {
  name: string;
  icon: string;
  category: string;
}

interface RawApp {
  pkg: string;
  name: string;
  icon: string;
  category: string;
  is_builtin: boolean;
}

function mapApp(raw: RawApp): AppReference {
  return {
    pkg: raw.pkg,
    name: raw.name,
    icon: raw.icon,
    category: raw.category,
    isBuiltin: raw.is_builtin
  };
}

@Injectable({
  providedIn: 'root'
})
export class AppRegistryService {
  private http = inject(HttpClient);

  public apps = signal<AppReference[]>([]);

  constructor() {
    this.loadApps().subscribe();
  }

  /**
   * Fetches the full app registry from the backend and replaces `apps`.
   * Called on service init and after every mutation.
   */
  public loadApps(): Observable<RawApp[]> {
    return this.http.get<RawApp[]>('/api/apps').pipe(
      tap({
        next: (response) => this.apps.set(response.map(mapApp)),
        error: (err) => console.error('Failed to load app registry:', err)
      })
    );
  }

  public createApp(payload: AppWritePayload): Observable<AppReference> {
    return this.http.post<RawApp>('/api/apps', payload).pipe(
      tap(() => this.loadApps().subscribe()),
      map((raw) => mapApp(raw))
    );
  }

  public updateApp(pkg: string, payload: AppUpdatePayload): Observable<AppReference> {
    return this.http.put<RawApp>(`/api/apps/${pkg}`, payload).pipe(
      tap(() => this.loadApps().subscribe()),
      map((raw) => mapApp(raw))
    );
  }

  public deleteApp(pkg: string): Observable<{ status: string; pkg: string }> {
    return this.http.delete<{ status: string; pkg: string }>(`/api/apps/${pkg}`).pipe(
      tap(() => this.loadApps().subscribe())
    );
  }
}
