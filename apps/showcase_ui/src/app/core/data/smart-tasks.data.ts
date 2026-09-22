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
 * Recognized Android App Package Registry
 */
export const APP_REGISTRY: Record<string, AppReference> = {
  // Google Suite & System
  'com.google.android.apps.maps': { name: 'Maps', icon: 'explore', pkg: 'com.google.android.apps.maps', category: 'navigation' },
  'com.google.android.gm': { name: 'Gmail', icon: 'mail', pkg: 'com.google.android.gm', category: 'productivity' },
  'com.android.chrome': { name: 'Chrome', icon: 'public', pkg: 'com.android.chrome', category: 'browser' },
  'com.google.android.youtube': { name: 'YouTube', icon: 'smart_display', pkg: 'com.google.android.youtube', category: 'entertainment' },
  'com.android.settings': { name: 'Settings', icon: 'settings', pkg: 'com.android.settings', category: 'system' },
  'com.google.android.deskclock': { name: 'Clock', icon: 'timer', pkg: 'com.google.android.deskclock', category: 'utility' },
  'com.android.deskclock': { name: 'Clock', icon: 'timer', pkg: 'com.android.deskclock', category: 'utility' },
  'com.google.android.calculator': { name: 'Calculator', icon: 'calculate', pkg: 'com.google.android.calculator', category: 'utility' },
  'com.android.calculator2': { name: 'Calculator', icon: 'calculate', pkg: 'com.android.calculator2', category: 'utility' },
  'com.google.android.apps.photos': { name: 'Photos', icon: 'photo_library', pkg: 'com.google.android.apps.photos', category: 'media' },
  'com.google.android.calendar': { name: 'Calendar', icon: 'calendar_month', pkg: 'com.google.android.calendar', category: 'productivity' },
  'com.google.android.keep': { name: 'Keep Notes', icon: 'note_alt', pkg: 'com.google.android.keep', category: 'productivity' },
  'com.android.vending': { name: 'Play Store', icon: 'storefront', pkg: 'com.android.vending', category: 'tools' },
  'com.google.android.apps.messaging': { name: 'Messages', icon: 'chat', pkg: 'com.google.android.apps.messaging', category: 'communication' },

  // Popular Ecosystem Apps
  'com.tencent.mm': { name: 'WeChat', icon: 'forum', pkg: 'com.tencent.mm', category: 'social' },
  'com.xingin.xhs': { name: 'Xiaohongshu', icon: 'auto_stories', pkg: 'com.xingin.xhs', category: 'social' },
  'com.sankuai.meituan': { name: 'Meituan', icon: 'restaurant', pkg: 'com.sankuai.meituan', category: 'lifestyle' },
  'com.dianping.v1': { name: 'Dianping', icon: 'star', pkg: 'com.dianping.v1', category: 'lifestyle' },
  'tv.danmaku.bili': { name: 'Bilibili', icon: 'video_library', pkg: 'tv.danmaku.bili', category: 'entertainment' },
  'com.eg.android.AlipayGphone': { name: 'Alipay', icon: 'account_balance_wallet', pkg: 'com.eg.android.AlipayGphone', category: 'finance' },
  'com.netease.cloudmusic': { name: 'NetEase Music', icon: 'headphones', pkg: 'com.netease.cloudmusic', category: 'entertainment' },
  'com.spotify.music': { name: 'Spotify', icon: 'music_note', pkg: 'com.spotify.music', category: 'entertainment' }
};

