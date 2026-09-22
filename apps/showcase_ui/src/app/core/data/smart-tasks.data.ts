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

export interface AppReference {
  name: string;
  icon: string;
  pkg?: string;
  category?: string;
  isBuiltin?: boolean;
}

export type SuggestionCategory =
  | 'all'
  | 'flash'
  | 'pro'
  | 'cross_app'
  | 'monitor';

export interface SmartSuggestion {
  id: string;
  title: string;
  description: string;
  goal: string;
  profile: 'flash' | 'pro';
  category: 'flash' | 'pro' | 'cross_app' | 'monitor';
  tag: string;
  apps: AppReference[];
  requiredPackages?: string[];
  matchMode?: 'any' | 'all';
  priority?: number;
  isBuiltin?: boolean;
}

/**
 * Fixed set of Material Symbols icon names offered when adding or editing
 * an app in the registry. This stays a static frontend list (unlike the
 * app registry itself, which is backend-owned) since it's UI-picker
 * metadata that only changes per-release, not per-user.
 */
export const ICON_OPTIONS: string[] = [
  'account_balance_wallet',
  'auto_stories',
  'calculate',
  'calendar_month',
  'chat',
  'explore',
  'forum',
  'headphones',
  'mail',
  'music_note',
  'note_alt',
  'photo_library',
  'public',
  'restaurant',
  'settings',
  'smart_display',
  'star',
  'storefront',
  'timer',
  'video_library'
];
