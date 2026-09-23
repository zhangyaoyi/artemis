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

import { Component, signal, computed, effect, inject, OnInit, OnDestroy, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AgentService } from '../../services/agent.service';
import { SystemService } from '../../services/system.service';
import {
  AdbServerConnectionResult,
  AdbServerDevice,
  DeviceInfo,
  ProbeResult
} from '../../core/models/system.model';
import {
  AppReference,
  SmartSuggestion,
  SuggestionCategory
} from '../../core/data/smart-tasks.data';
import { TaskPresetWritePayload, TaskRecommendationService } from '../../core/services/task-recommendation.service';
import { TaskPresetFormComponent } from '../../components/task-preset-form/task-preset-form.component';
import {
  DEFAULT_EXPLORER_MODE,
  DEFAULT_VERIFICATION_LEVEL,
  EXPLORER_MODES,
  ExplorerModeId,
  TuningLevel,
  VERIFICATION_LEVELS,
  VerificationLevelId,
  levelIndex,
  notchPercent
} from '../../core/models/pro-tuning.model';

export type TuningKind = 'verify' | 'explore';

/** One 2x2 px square of the "maxed out" dither texture drawn over a slider rail. */
export interface DitherPixel {
  /** Horizontal position as a percentage of the rail width. */
  x: number;
  /** Row offset in px (rail is 6 px tall, three 2 px rows). */
  y: number;
  /** Resting opacity; squares near the thumb are stronger. */
  opacity: number;
  /** Animation delay in ms so the texture spreads leftwards from the thumb. */
  delay: number;
}

/**
 * Seeded pixels keep the slider texture stable across renders.
 * Delays increase with distance from the thumb to animate from right to left.
 */
function buildDitherPixels(count = 260, seed = 7): DitherPixel[] {
  let state = seed >>> 0;
  const rand = (): number => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
  const pixels: DitherPixel[] = [];
  for (let i = 0; i < count; i++) {
    const x = rand() * 100;
    const y = Math.floor(rand() * 3) * 2;
    pixels.push({
      x: Math.round(x * 10) / 10,
      y,
      opacity: Math.round((0.35 + 0.4 * rand()) * 100) / 100,
      // 8 ms per percent: the front takes ~0.8 s to reach the left end.
      delay: Math.round((100 - x) * 8)
    });
  }
  return pixels;
}

/** Shared view model for the verification and screen-reading sliders. */
export interface TuningSliderVm {
  kind: TuningKind;
  name: string;
  /** One-word meaning of each end of the track, e.g. ["Off", "Strict"]. */
  ends: readonly [string, string];
  ladder: readonly TuningLevel[];
  index: number;
  level: TuningLevel;
  /** 0..1 position of the thumb along the track. */
  fraction: number;
}

export type { AppReference, SmartSuggestion, SuggestionCategory };

type AdbGuideTab = 'emulator' | 'usb' | 'wifi' | 'remote';


@Component({
  selector: 'app-home',
  standalone: true,
  imports: [FormsModule, TaskPresetFormComponent],
  templateUrl: './home.component.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './home.component.scss'
})
export class HomeComponent implements OnInit, OnDestroy {
  public agentService = inject(AgentService);
  public systemService = inject(SystemService);
  public taskRecService = inject(TaskRecommendationService);
  private router = inject(Router);

  // High-level navigation mode: 'diagnostics' (System Setup Guide) vs 'launcher' (Task Execution)
  public activeTab = signal<'diagnostics' | 'launcher'>('launcher');

  // Interactive guide sub-tab inside the ADB section
  public activeAdbGuideTab = signal<AdbGuideTab>('emulator');
  public emulatorSetupMode = signal<'studio' | 'cli'>('studio');

  // Interactive guide tab for LLM / OCR credentials: 'gemini' | 'openai' | 'anthropic'
  public modelSetupMode = signal<'gemini' | 'openai' | 'anthropic'>('gemini');
  public showAdvancedInspector = signal<boolean>(false);
  public showOcrConfig = signal<boolean>(false);
  public showFullConfigFile = signal<boolean>(false);

  // Model & Environment configuration from backend
  public modelConfigEnv = computed(() => this.systemService.modelConfigEnv());

  // Google Gemini API Key State
  public geminiKeyInput = signal<string>('');
  public showGeminiKey = signal<boolean>(false);
  public isSavingGeminiKey = signal<boolean>(false);
  public isTestingGeminiKey = signal<boolean>(false);
  public geminiSaveMessage = signal<string | null>(null);
  public geminiSaveError = signal<string | null>(null);
  public isGeminiKeyEdited = signal<boolean>(false);

  // OpenAI-compatible Setup State
  public openaiBaseUrlInput = signal<string>('');
  public openaiModelInput = signal<string>('');
  public openaiKeyInput = signal<string>('');
  public showOpenaiKey = signal<boolean>(false);
  public isSavingOpenaiConfig = signal<boolean>(false);
  public isTestingOpenaiConfig = signal<boolean>(false);
  public openaiSaveMessage = signal<string | null>(null);
  public openaiSaveError = signal<string | null>(null);
  public isOpenaiKeyEdited = signal<boolean>(false);

  // Anthropic-compatible Setup State
  public anthropicBaseUrlInput = signal<string>('');
  public anthropicModelInput = signal<string>('');
  public anthropicKeyInput = signal<string>('');
  public showAnthropicKey = signal<boolean>(false);
  public isSavingAnthropicConfig = signal<boolean>(false);
  public isTestingAnthropicConfig = signal<boolean>(false);
  public anthropicSaveMessage = signal<string | null>(null);
  public anthropicSaveError = signal<string | null>(null);
  public isAnthropicKeyEdited = signal<boolean>(false);

  // Vision OCR API Key State
  public ocrKeyInput = signal<string>('');
  public showOcrKey = signal<boolean>(false);
  public isSavingOcrKey = signal<boolean>(false);
  public isTestingOcrKey = signal<boolean>(false);
  public ocrSaveMessage = signal<string | null>(null);
  public ocrSaveError = signal<string | null>(null);
  public isOcrKeyEdited = signal<boolean>(false);

  // Clipboard copy state tracker for interactive feedback
  public copiedId = signal<string | null>(null);

  // Diagnostic re-check state
  public isRefreshingDiagnostics = signal<boolean>(false);

  // Wireless ADB Interactive connection signals
  public wifiHost = signal<string>('192.168.1.100');
  public wifiPort = signal<string>('5555');
  public isConnectingWifi = signal<boolean>(false);
  public wifiConnectMessage = signal<string | null>(null);
  public wifiConnectError = signal<string | null>(null);
  public adbRestartFeedback = signal<string | null>(null);
  public showConnectionMethods = signal<boolean>(false);

  // ADB server endpoint connection state
  public remoteAdbHost = signal<string>('127.0.0.1');
  public remoteAdbPort = signal<string>('5038');
  public rememberRemoteAdb = signal<boolean>(true);
  public isConnectingRemoteAdb = signal<boolean>(false);
  public isActivatingRemoteAdb = signal<boolean>(false);
  public isSwitchingToLocalAdb = signal<boolean>(false);
  public remoteAdbMessage = signal<string | null>(null);
  public remoteAdbError = signal<string | null>(null);
  public remoteAdbDevices = signal<AdbServerDevice[]>([]);
  public remoteAdbProbeResult = signal<AdbServerConnectionResult | null>(null);
  public adbServerStatus = computed(() => this.systemService.adbServerStatus());
  public isRemoteAdbServer = computed(() => this.systemService.isRemoteAdbServer());
  public remoteAdbHasReadyDevice = computed(() =>
    this.remoteAdbDevices().some(device => device.state === 'device')
  );
  public isProbedRemoteAdbActive = computed(() => {
    const tested = this.remoteAdbProbeResult()?.endpoint;
    const active = this.adbServerStatus()?.endpoint;
    return !!tested && !!active && tested.identity === active.identity;
  });

  public wifiCommand = computed(() => {
    const h = this.wifiHost().trim() || '<phone-ip>';
    const p = this.wifiPort().trim() || '5555';
    return `adb connect ${h}:${p}`;
  });

  // Task execution parameters
  public selectedProfile = signal<'flash' | 'pro'>('flash');
  public taskGoal = signal<string>('');
  public isSubmitting = signal<boolean>(false);
  public errorMessage = signal<string | null>(null);

  // Pro Mode Outputter & Structured Output Configuration
  public expectedOutput = signal<string>('');
  public enableOutputter = signal<boolean>(true);
  public showOutputterDrawer = signal<boolean>(false);

  // Slider indexes map to the API ids in VERIFICATION_LEVELS / EXPLORER_MODES.
  public readonly verificationLevels = VERIFICATION_LEVELS;
  public readonly explorerModes = EXPLORER_MODES;
  public verificationIndex = signal<number>(
    levelIndex(VERIFICATION_LEVELS, DEFAULT_VERIFICATION_LEVEL, DEFAULT_VERIFICATION_LEVEL)
  );
  public explorerIndex = signal<number>(
    levelIndex(EXPLORER_MODES, DEFAULT_EXPLORER_MODE, DEFAULT_EXPLORER_MODE)
  );
  /** Effective defaults from the backend config (`GET /api/run/defaults`). */
  private tuningDefaults = signal<{ verification: VerificationLevelId; explorer: ExplorerModeId }>({
    verification: DEFAULT_VERIFICATION_LEVEL,
    explorer: DEFAULT_EXPLORER_MODE
  });
  /** True once the user moved a slider; backend defaults then stop overriding it. */
  private tuningTouched = signal<boolean>(false);
  /** Which slider's hover card is open (while hovering, dragging, or focused). */
  public activeTuningTip = signal<TuningKind | null>(null);
  /** Pixel cloud drawn over a rail once its slider reaches the last notch. */
  public readonly ditherPixels: readonly DitherPixel[] = buildDitherPixels();

  public verificationLevel = computed<TuningLevel<VerificationLevelId>>(
    () => VERIFICATION_LEVELS[this.verificationIndex()]
  );
  public explorerMode = computed<TuningLevel<ExplorerModeId>>(
    () => EXPLORER_MODES[this.explorerIndex()]
  );
  public isTuningDefault = computed<boolean>(() => {
    const d = this.tuningDefaults();
    return this.verificationLevel().id === d.verification && this.explorerMode().id === d.explorer;
  });
  public tuningSliders = computed<TuningSliderVm[]>(() => {
    const vi = this.verificationIndex();
    const ei = this.explorerIndex();
    return [
      {
        kind: 'verify',
        name: 'Result check',
        ends: ['Off', 'Strict'],
        ladder: VERIFICATION_LEVELS,
        index: vi,
        level: VERIFICATION_LEVELS[vi],
        fraction: notchPercent(vi, VERIFICATION_LEVELS.length) / 100
      },
      {
        kind: 'explore',
        name: 'Screen reading',
        ends: ['Faster', 'Sharper'],
        ladder: EXPLORER_MODES,
        index: ei,
        level: EXPLORER_MODES[ei],
        fraction: notchPercent(ei, EXPLORER_MODES.length) / 100
      }
    ];
  });

  public notchFraction(index: number, count: number): number {
    return notchPercent(index, count) / 100;
  }

  public setTuningIndex(kind: TuningKind, raw: number | string): void {
    const idx = Math.round(Number(raw));
    if (!Number.isFinite(idx)) return;
    const ladder = kind === 'verify' ? VERIFICATION_LEVELS : EXPLORER_MODES;
    const clamped = Math.min(Math.max(idx, 0), ladder.length - 1);
    this.tuningTouched.set(true);
    if (kind === 'verify') {
      this.verificationIndex.set(clamped);
    } else {
      this.explorerIndex.set(clamped);
    }
    // Keyboard nudges and drags should keep the explanation visible.
    this.activeTuningTip.set(kind);
  }

  public showTuningTip(kind: TuningKind): void {
    this.activeTuningTip.set(kind);
  }

  public hideTuningTip(kind: TuningKind): void {
    if (this.activeTuningTip() === kind) {
      this.activeTuningTip.set(null);
    }
  }

  public resetTuning(): void {
    const d = this.tuningDefaults();
    this.verificationIndex.set(levelIndex(VERIFICATION_LEVELS, d.verification, DEFAULT_VERIFICATION_LEVEL));
    this.explorerIndex.set(levelIndex(EXPLORER_MODES, d.explorer, DEFAULT_EXPLORER_MODE));
    this.tuningTouched.set(false);
  }

  /** Pull the effective config defaults so the sliders start where artemis.jsonc is. */
  private loadProTuningDefaults(): void {
    this.agentService.getProTuningDefaults().subscribe({
      next: (res) => {
        const vIdx = levelIndex(VERIFICATION_LEVELS, res?.verification_level, DEFAULT_VERIFICATION_LEVEL);
        const eIdx = levelIndex(EXPLORER_MODES, res?.explorer_mode, DEFAULT_EXPLORER_MODE);
        this.tuningDefaults.set({
          verification: VERIFICATION_LEVELS[vIdx].id,
          explorer: EXPLORER_MODES[eIdx].id
        });
        if (!this.tuningTouched()) {
          this.verificationIndex.set(vIdx);
          this.explorerIndex.set(eIdx);
        }
      },
      // Defaults are a convenience; the built-in ladder defaults already apply.
      error: () => undefined
    });
  }

  public toggleOutputterDrawer(): void {
    this.showOutputterDrawer.update((v) => !v);
  }

  public applyOutputPreset(preset: string): void {
    if (this.expectedOutput() === preset) {
      this.expectedOutput.set('');
    } else {
      this.expectedOutput.set(preset);
      this.showOutputterDrawer.set(true);
    }
  }

  // Smart intent detection for model recommendation
  public isIntentSuggestingPro = computed<boolean>(() => {
    const text = this.taskGoal().toLowerCase();
    if (!text.trim()) return false;
    const keywords = [
      'monitor', 'polling', 'poll', 'wait until', 'loop', 'keep watching',
      'crash', 'logcat', 'troubleshoot', 'diagnose', 'debug', 'investigate',
      'compare', 'extract', 'summarize', 'report',
      '监控', '轮询', '等待', '一直', '直到', '崩溃', '闪退', '排查', '分析日志', '对比', '总结'
    ];
    return keywords.some(k => text.includes(k));
  });

  public showIntentSuggestion = computed<boolean>(() => {
    return this.isIntentSuggestingPro() && this.selectedProfile() === 'flash';
  });

  // Computed helper states delegating to SystemService
  public isReady = computed(() => this.systemService.isReady());
  public hasReadinessReport = computed(() => this.systemService.hasReadinessReport());
  public isLoading = computed(() => this.systemService.isLoading());
  public isRestartingAdb = computed(() => this.systemService.isRestartingAdb());
  public launchingAvd = computed(() => this.systemService.launchingAvd());
  public emulatorLaunchState = computed(() => this.systemService.emulatorLaunchState());
  public isEmulatorLaunching = computed(() => this.systemService.isEmulatorLaunching());
  public showLaunchLogs = signal<boolean>(false);
  
  // Probes
  public pythonProbe = computed(() => this.systemService.pythonProbe());
  public configProbe = computed(() => this.systemService.configProbe());
  public adbProbe = computed(() => this.systemService.adbProbe());
  public llmProbe = computed(() => this.systemService.llmProbe());
  public geminiProbe = computed(() => this.systemService.geminiProbe());
  public ocrProbe = computed(() => this.systemService.ocrProbe());
  public toolchainProbe = computed(() => this.systemService.toolchainProbe());

  // Step-level readiness
  public isEnvironmentReady = computed(() => this.systemService.isEnvironmentReady());
  public isCredentialsReady = computed(() => this.systemService.isCredentialsReady());
  public isSkipCredentialsCheck = computed(() => this.systemService.isSkipCredentialsCheck());
  public isDeviceReady = computed(() => this.systemService.isDeviceReady());

  // Device information
  public activeDevice = computed(() => this.systemService.activeDevice());
  public connectedDevices = computed(() => this.systemService.connectedDevices());
  public installedAvds = computed(() => this.systemService.installedAvds());
  public emulatorPath = computed(() => this.systemService.emulatorPath());
  public isEmulatorInPath = computed(() => this.systemService.isEmulatorInPath());
  public totalStepCount = computed(() => this.systemService.totalStepCount());
  public passedStepCount = computed(() => this.systemService.passedStepCount());
  public blockerCount = computed(() => this.systemService.blockerCount());
  public passedBlockerCount = computed(() => this.systemService.passedBlockerCount());

  // Configured LLM providers from probe metadata
  public configuredLlmProviders = computed<any[]>(() => {
    const meta = this.llmProbe()?.metadata;
    if (meta && Array.isArray(meta['providers'])) {
      return meta['providers'];
    }
    return [];
  });

  // Multi-OS detection & active OS selection
  public selectedOs = signal<'linux' | 'darwin' | 'windows' | null>(null);
  public effectiveOs = computed<'linux' | 'darwin' | 'windows'>(() => {
    return this.selectedOs() || this.systemService.osType();
  });

  public oneClickSetupCmd = computed(() => {
    const os = this.effectiveOs();
    if (os === 'windows') {
      return 'powershell -ExecutionPolicy Bypass -File scripts/install_deps.ps1';
    }
    return 'bash scripts/install_deps.sh';
  });

  public adbInstallCmd = computed(() => {
    const os = this.effectiveOs();
    if (os === 'windows') {
      return 'winget install Google.PlatformTools';
    }
    if (os === 'darwin') {
      return 'brew install android-platform-tools';
    }
    return 'sudo apt-get install -y adb';
  });

  public toolchainInstallCmd = computed(() => {
    const os = this.effectiveOs();
    if (os === 'windows') {
      return 'winget install Gyan.FFmpeg Genymobile.scrcpy';
    }
    if (os === 'darwin') {
      return 'brew install ffmpeg scrcpy';
    }
    return 'sudo apt-get install -y ffmpeg scrcpy';
  });

  public emuHypervisorTitle = computed(() => {
    const os = this.effectiveOs();
    if (os === 'windows') return 'Enable Windows Hypervisor Platform (WHPX)';
    if (os === 'darwin') return 'Verify macOS Hypervisor / Install Tools';
    return 'Enable KVM Hardware Acceleration (Linux)';
  });

  public emuHypervisorDesc = computed(() => {
    const os = this.effectiveOs();
    if (os === 'windows') return 'Enable Windows Hypervisor Platform in PowerShell (Run as Administrator):';
    if (os === 'darwin') return 'macOS uses native Hypervisor.framework. Install SDK tools via Homebrew (or Studio):';
    return 'Ensure virtualization permissions are granted to your user account:';
  });

  public emuHypervisorCmd = computed(() => {
    const os = this.effectiveOs();
    if (os === 'windows') return 'Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform';
    if (os === 'darwin') return 'brew install --cask android-commandlinetools';
    return 'sudo apt-get install -y qemu-kvm libvirt-daemon-system && sudo adduser $USER kvm';
  });

  public emuSdkInstallCmd = computed(() => {
    const os = this.effectiveOs();
    if (os === 'darwin') {
      return 'sdkmanager --install "system-images;android-34;google_apis;arm64-v8a" "emulator" "platform-tools"';
    }
    return 'sdkmanager --install "system-images;android-34;google_apis;x86_64" "emulator" "platform-tools"';
  });

  public emuCreateAvdCmd = computed(() => {
    const os = this.effectiveOs();
    if (os === 'darwin') {
      return 'avdmanager create avd -n Pixel_8_API_34 -k "system-images;android-34;google_apis;arm64-v8a" --device "pixel_8"';
    }
    return 'avdmanager create avd -n Pixel_8_API_34 -k "system-images;android-34;google_apis;x86_64" --device "pixel_8"';
  });

  // Flag indicating whether Google Cloud Vision OCR is configured
  public isOcrConfigured = computed<boolean>(() => {
    const meta = this.ocrProbe()?.metadata;
    return meta?.['configured'] === true;
  });

  public currentApiKey = computed<string>(() => this.systemService.currentApiKey());
  public apiKeysMap = computed<Record<string, string>>(() => this.systemService.apiKeysMap());

  public savedGeminiKey = computed<string>(() => {
    const keys = this.apiKeysMap();
    return keys['google'] || this.currentApiKey() || '';
  });

  public isGeminiModified = computed<boolean>(() => {
    return this.geminiKeyInput().trim() !== this.savedGeminiKey().trim();
  });

  public savedOpenaiKey = computed<string>(() => this.apiKeysMap()['openai'] || '');
  public isOpenaiKeyModified = computed<boolean>(() =>
    this.openaiKeyInput().trim() !== this.savedOpenaiKey().trim()
  );

  public savedAnthropicKey = computed<string>(() => this.apiKeysMap()['anthropic'] || '');
  public isAnthropicKeyModified = computed<boolean>(() =>
    this.anthropicKeyInput().trim() !== this.savedAnthropicKey().trim()
  );

  public savedOcrKey = computed<string>(() => {
    const keys = this.apiKeysMap();
    return keys['ocr'] || '';
  });

  public isOcrModified = computed<boolean>(() => {
    return this.ocrKeyInput().trim() !== this.savedOcrKey().trim();
  });

  // Suggestion category filter & shuffle state
  public selectedCategory = signal<SuggestionCategory>('all');
  public shuffleOffset = signal<number>(0);

  public categoryTabs = computed<string[]>(() =>
    Array.from(new Set(this.taskRecService.allTasks().map(task => task.category)))
  );

  // Set of installed package strings from active device
  public installedPackages = computed<Set<string>>(() => {
    const pkgs = this.activeDevice()?.installed_packages;
    if (pkgs && Array.isArray(pkgs)) {
      return new Set(pkgs);
    }
    return new Set();
  });

  public filteredSuggestions = computed<SmartSuggestion[]>(() => {
    return this.taskRecService.filterAndRankTasks(
      this.installedPackages(),
      this.selectedCategory(),
      this.shuffleOffset()
    );
  });

  // Recommended Tasks CRUD modal state
  public showTaskModal = signal<boolean>(false);
  public editingTask = signal<SmartSuggestion | null>(null);

  // Error shown inside the create/edit modal itself (the page-level
  // errorMessage banner sits behind the modal's full-viewport overlay, so
  // it's invisible while the modal is open).
  public taskModalError = signal<string | null>(null);

  public openAddTaskModal(): void {
    this.editingTask.set(null);
    this.taskModalError.set(null);
    this.showTaskModal.set(true);
  }

  public openEditTaskModal(item: SmartSuggestion, event: Event): void {
    event.stopPropagation();
    this.editingTask.set(item);
    this.taskModalError.set(null);
    this.showTaskModal.set(true);
  }

  public closeTaskModal(): void {
    this.showTaskModal.set(false);
    this.editingTask.set(null);
    this.taskModalError.set(null);
  }

  public saveTaskPreset(payload: TaskPresetWritePayload): void {
    const editing = this.editingTask();
    const request$ = editing
      ? this.taskRecService.updateTask(editing.id, payload)
      : this.taskRecService.createTask(payload);
    request$.subscribe({
      next: () => this.closeTaskModal(),
      error: (err) => {
        const message = err?.error?.detail || 'Failed to save task preset.';
        this.errorMessage.set(message);
        this.taskModalError.set(message);
        // The row may already be gone (e.g. deleted in another tab, 404 on
        // update) or the catalog may otherwise be stale -- refresh so the
        // grid self-corrects instead of showing a stale card.
        this.taskRecService.loadTasks().subscribe();
      }
    });
  }

  public deleteTaskPreset(item: SmartSuggestion, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Delete "${item.title}"?`)) {
      return;
    }
    this.taskRecService.deleteTask(item.id).subscribe({
      error: (err) => {
        this.errorMessage.set(err?.error?.detail || 'Failed to delete task preset.');
        // Same self-correction as above: a 404 here means the row was
        // already deleted elsewhere, so re-sync the catalog.
        this.taskRecService.loadTasks().subscribe();
      }
    });
  }




  private focusListener = () => {
    // Silently re-check environment when user returns to the browser tab
    this.systemService.fetchReadiness().subscribe();
    // Also retry the Recommended Tasks catalog load: if the initial load
    // failed (e.g. backend still starting up), returning to the tab is a
    // natural moment to try again since it's already the established retry
    // trigger for readiness above.
    this.taskRecService.loadTasks().subscribe();
  };

  constructor() {
    effect(() => {
      const keys = this.systemService.apiKeysMap();
      const current = this.systemService.currentApiKey();
      const googleKey = keys['google'] || current || '';
      const ocrKey = keys['ocr'] || '';
      const openaiKey = keys['openai'] || '';
      const anthropicKey = keys['anthropic'] || '';
      if (!this.isGeminiKeyEdited()) {
        this.geminiKeyInput.set(googleKey);
      }
      if (!this.isOcrKeyEdited()) {
        this.ocrKeyInput.set(ocrKey);
      }
      if (!this.isOpenaiKeyEdited()) {
        this.openaiKeyInput.set(openaiKey);
      }
      if (!this.isAnthropicKeyEdited()) {
        this.anthropicKeyInput.set(anthropicKey);
      }
    });

    effect(() => {
      const cfg = this.modelConfigEnv();
      if (!cfg) return;
      const provider = (cfg.default_model?.provider || '').toLowerCase();
      const model = cfg.default_model?.model || '';
      const apiBase = cfg.default_model?.api_base || '';
      // openrouter/xai/ollama/vllm/custom all share the OpenAI-compatible
      // ChatOpenAI dispatch branch in artemis/llm/router.py, so they all
      // land on the "OpenAI 兼容" card too.
      const openaiLikeProviders = ['openai', 'openrouter', 'xai', 'ollama', 'vllm', 'custom'];
      if (provider === 'anthropic') {
        this.anthropicModelInput.set(model);
        this.anthropicBaseUrlInput.set(apiBase);
      } else if (openaiLikeProviders.includes(provider)) {
        this.openaiModelInput.set(model);
        // A legacy provider (openrouter/xai/ollama/vllm/custom) with no
        // explicit api_base was actually resolving against that provider's
        // own real endpoint (artemis/llm/router.py's per-provider default),
        // not api.openai.com. Pre-fill the field with that real default so
        // a Save without editing Base URL doesn't silently re-point traffic
        // to OpenAI's official API.
        this.openaiBaseUrlInput.set(apiBase || this.legacyProviderDefaultBaseUrl(provider));
      }
    });
  }

  ngOnInit(): void {

    this.loadProTuningDefaults();
    // Initial fetch of system readiness & model configuration
    this.systemService.fetchReadiness().subscribe();
    // Retry the Recommended Tasks catalog load on component init. The
    // service already fetches it once from its constructor, but that
    // request can fail (e.g. backend still starting up) and the service
    // has no retry of its own -- a failed one-shot load would otherwise
    // leave `allTasks` permanently empty. This is a second, independent
    // attempt; loadTasks() is idempotent (it just replaces `allTasks` with
    // whatever the server returns), so a redundant successful fetch here is
    // harmless.
    this.taskRecService.loadTasks().subscribe();
    this.systemService.fetchModelConfigEnv().subscribe({
      next: cfg => {
        // Preselect the setup mode that matches the configured default provider.
        // openrouter/xai/ollama/vllm/custom all share the OpenAI-compatible
        // ChatOpenAI dispatch branch in artemis/llm/router.py, so they all
        // land on the "OpenAI 兼容" card too.
        const provider = (cfg.default_model?.provider || '').toLowerCase();
        const openaiLikeProviders = ['openai', 'openrouter', 'xai', 'ollama', 'vllm', 'custom'];
        if (provider === 'anthropic') {
          this.setModelSetupMode('anthropic');
        } else if (openaiLikeProviders.includes(provider)) {
          this.setModelSetupMode('openai');
        }
      },
      error: () => {}
    });
    this.systemService.fetchAdbServerStatus().subscribe({
      next: status => {
        if (status.endpoint.mode === 'remote') {
          this.remoteAdbHost.set(status.endpoint.host);
          this.remoteAdbPort.set(String(status.endpoint.port));
          this.activeAdbGuideTab.set('remote');
        }
      },
      error: () => {}
    });

    window.addEventListener('focus', this.focusListener);
  }

  ngOnDestroy(): void {
    window.removeEventListener('focus', this.focusListener);
  }

  public setTab(tab: 'diagnostics' | 'launcher'): void {
    this.activeTab.set(tab);
    if (tab === 'diagnostics') {
      this.systemService.fetchReadiness().subscribe();
      this.systemService.fetchModelConfigEnv().subscribe();
    }
  }

  public setSelectedOs(os: 'linux' | 'darwin' | 'windows'): void {
    this.selectedOs.set(os);
  }

  public setAdbGuideTab(tab: AdbGuideTab): void {
    this.activeAdbGuideTab.set(tab);
    this.remoteAdbError.set(null);
    this.remoteAdbMessage.set(null);
  }

  public setEmulatorSetupMode(mode: 'studio' | 'cli'): void {
    this.emulatorSetupMode.set(mode);
  }

  public setModelSetupMode(mode: 'gemini' | 'openai' | 'anthropic'): void {
    this.modelSetupMode.set(mode);
  }

  /**
   * The real endpoint a legacy provider without an explicit api_base
   * actually resolves against, per artemis/llm/router.py's own per-provider
   * fallback -- used to pre-fill the OpenAI-compatible card's Base URL field
   * so re-saving doesn't silently switch it to OpenAI's official endpoint.
   */
  private legacyProviderDefaultBaseUrl(provider: string): string {
    switch (provider) {
      case 'openrouter': return 'https://openrouter.ai/api/v1';
      case 'xai': return 'https://api.x.ai/v1';
      case 'ollama':
      case 'vllm':
      case 'custom':
        return 'http://localhost:8000/v1';
      default:
        return '';
    }
  }

  public toggleAdvancedInspector(): void {
    this.showAdvancedInspector.update(v => !v);
    if (this.showAdvancedInspector()) {
      // Expanding the advanced panel means the user intends to manage
      // config/credentials by hand; don't block the launcher on the
      // automated credentials probe while they do that.
      this.systemService.setSkipCredentialsCheck(true);
      this.systemService.fetchModelConfigEnv().subscribe();
    }
  }

  public toggleFullConfigFile(): void {
    this.showFullConfigFile.update(v => !v);
  }

  public toggleGeminiKeyVisibility(): void {
    this.showGeminiKey.update(v => !v);
  }

  public toggleOcrKeyVisibility(): void {
    this.showOcrKey.update(v => !v);
  }

  public toggleOcrConfig(): void {
    this.showOcrConfig.update(v => !v);
  }

  public onGeminiKeyChange(val: string): void {
    this.geminiKeyInput.set(val);
    this.isGeminiKeyEdited.set(true);
    this.geminiSaveError.set(null);
    this.geminiSaveMessage.set(null);
  }

  public onOcrKeyChange(val: string): void {
    this.ocrKeyInput.set(val);
    this.isOcrKeyEdited.set(true);
    this.ocrSaveError.set(null);
    this.ocrSaveMessage.set(null);
  }

  public saveGeminiKey(): void {
    const key = this.geminiKeyInput().trim();
    if (!key) return;
    this.isSavingGeminiKey.set(true);
    this.geminiSaveError.set(null);
    this.geminiSaveMessage.set(null);

    this.systemService.updateApiKey('google', key, true).subscribe({
      next: (res) => {
        this.isSavingGeminiKey.set(false);
        this.isGeminiKeyEdited.set(false);
        this.geminiSaveMessage.set(res?.message || '✓ Gemini API key verified & saved successfully.');
        setTimeout(() => this.geminiSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isSavingGeminiKey.set(false);
        this.geminiSaveError.set(err?.error?.detail || err?.message || 'Failed to update Gemini API key.');
      }
    });
  }

  public clearGeminiKey(): void {
    this.geminiKeyInput.set('');
    this.isGeminiKeyEdited.set(false);
    this.geminiSaveError.set(null);
    this.geminiSaveMessage.set(null);

    if (this.savedGeminiKey().trim()) {
      this.isSavingGeminiKey.set(true);
      this.systemService.updateApiKey('google', '', true).subscribe({
        next: (res) => {
          this.isSavingGeminiKey.set(false);
          this.geminiSaveMessage.set(res?.message || '✓ Gemini API key cleared.');
          setTimeout(() => this.geminiSaveMessage.set(null), 5000);
        },
        error: (err) => {
          this.isSavingGeminiKey.set(false);
          this.geminiSaveError.set(err?.error?.detail || err?.message || 'Failed to clear Gemini API key.');
        }
      });
    } else {
      this.geminiSaveMessage.set('✓ Gemini API key cleared.');
      setTimeout(() => this.geminiSaveMessage.set(null), 3000);
    }
  }

  public saveOcrKey(): void {
    const key = this.ocrKeyInput().trim();
    if (!key) return;
    this.isSavingOcrKey.set(true);
    this.ocrSaveError.set(null);
    this.ocrSaveMessage.set(null);

    this.systemService.updateApiKey('ocr', key, true).subscribe({
      next: (res) => {
        this.isSavingOcrKey.set(false);
        this.isOcrKeyEdited.set(false);
        this.ocrSaveMessage.set(res?.message || '✓ Vision OCR API key verified & saved.');
        setTimeout(() => this.ocrSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isSavingOcrKey.set(false);
        this.ocrSaveError.set(err?.error?.detail || err?.message || 'Failed to update Vision OCR key.');
      }
    });
  }

  public clearOcrKey(): void {
    this.ocrKeyInput.set('');
    this.isOcrKeyEdited.set(false);
    this.ocrSaveError.set(null);
    this.ocrSaveMessage.set(null);

    if (this.savedOcrKey().trim()) {
      this.isSavingOcrKey.set(true);
      this.systemService.updateApiKey('ocr', '', true).subscribe({
        next: (res) => {
          this.isSavingOcrKey.set(false);
          this.ocrSaveMessage.set(res?.message || '✓ Vision OCR API key cleared.');
          setTimeout(() => this.ocrSaveMessage.set(null), 5000);
        },
        error: (err) => {
          this.isSavingOcrKey.set(false);
          this.ocrSaveError.set(err?.error?.detail || err?.message || 'Failed to clear Vision OCR key.');
        }
      });
    } else {
      this.ocrSaveMessage.set('✓ Vision OCR API key cleared.');
      setTimeout(() => this.ocrSaveMessage.set(null), 3000);
    }
  }

  public testGeminiKey(): void {
    const key = this.geminiKeyInput().trim();
    if (!key) return;
    this.isTestingGeminiKey.set(true);
    this.geminiSaveError.set(null);
    this.geminiSaveMessage.set(null);

    this.systemService.testApiKey('google', key).subscribe({
      next: (res) => {
        this.isTestingGeminiKey.set(false);
        if (res?.valid) {
          this.geminiSaveMessage.set(res?.message || '✓ Gemini API key is valid!');
        } else {
          this.geminiSaveError.set(res?.message || 'Gemini API key verification failed.');
        }
        setTimeout(() => this.geminiSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isTestingGeminiKey.set(false);
        this.geminiSaveError.set(err?.error?.detail || err?.message || 'Gemini API key test failed.');
      }
    });
  }

  public onOpenaiConfigChange(): void {
    this.isOpenaiKeyEdited.set(true);
    this.openaiSaveError.set(null);
    this.openaiSaveMessage.set(null);
  }

  public saveOpenaiConfig(): void {
    const model = this.openaiModelInput().trim();
    if (!model) {
      this.openaiSaveError.set('Model name is required.');
      return;
    }
    this.isSavingOpenaiConfig.set(true);
    this.openaiSaveError.set(null);
    this.openaiSaveMessage.set(null);

    const key = this.openaiKeyInput().trim();
    const baseUrl = this.openaiBaseUrlInput().trim() || null;

    const saveKey$ = key
      ? this.systemService.updateApiKey('openai', key, true, baseUrl || undefined)
      : null;

    const afterKey = () => {
      this.systemService.saveDefaultModel('openai', model, baseUrl).subscribe({
        next: (res) => {
          this.isSavingOpenaiConfig.set(false);
          this.isOpenaiKeyEdited.set(false);
          this.openaiSaveMessage.set(res?.message || '✓ OpenAI-compatible config saved.');
          setTimeout(() => this.openaiSaveMessage.set(null), 5000);
        },
        error: (err) => {
          this.isSavingOpenaiConfig.set(false);
          this.openaiSaveError.set(err?.error?.detail || err?.message || 'Failed to save default model.');
        }
      });
    };

    if (saveKey$) {
      saveKey$.subscribe({ next: afterKey, error: (err) => {
        this.isSavingOpenaiConfig.set(false);
        this.openaiSaveError.set(err?.error?.detail || err?.message || 'Failed to update OpenAI API key.');
      }});
    } else {
      afterKey();
    }
  }

  public testOpenaiConfig(): void {
    const key = this.openaiKeyInput().trim();
    if (!key) return;
    this.isTestingOpenaiConfig.set(true);
    this.openaiSaveError.set(null);
    this.openaiSaveMessage.set(null);

    this.systemService.testApiKey('openai', key, this.openaiBaseUrlInput().trim() || undefined).subscribe({
      next: (res) => {
        this.isTestingOpenaiConfig.set(false);
        if (res?.valid) {
          this.openaiSaveMessage.set(res?.message || '✓ OpenAI-compatible endpoint is valid!');
        } else {
          this.openaiSaveError.set(res?.message || 'Endpoint verification failed.');
        }
        setTimeout(() => this.openaiSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isTestingOpenaiConfig.set(false);
        this.openaiSaveError.set(err?.error?.detail || err?.message || 'Endpoint test failed.');
      }
    });
  }

  public onAnthropicConfigChange(): void {
    this.isAnthropicKeyEdited.set(true);
    this.anthropicSaveError.set(null);
    this.anthropicSaveMessage.set(null);
  }

  public saveAnthropicConfig(): void {
    const model = this.anthropicModelInput().trim();
    if (!model) {
      this.anthropicSaveError.set('Model name is required.');
      return;
    }
    this.isSavingAnthropicConfig.set(true);
    this.anthropicSaveError.set(null);
    this.anthropicSaveMessage.set(null);

    const key = this.anthropicKeyInput().trim();
    const baseUrl = this.anthropicBaseUrlInput().trim() || null;

    const saveKey$ = key
      ? this.systemService.updateApiKey('anthropic', key, true, baseUrl || undefined)
      : null;

    const afterKey = () => {
      this.systemService.saveDefaultModel('anthropic', model, baseUrl).subscribe({
        next: (res) => {
          this.isSavingAnthropicConfig.set(false);
          this.isAnthropicKeyEdited.set(false);
          this.anthropicSaveMessage.set(res?.message || '✓ Anthropic-compatible config saved.');
          setTimeout(() => this.anthropicSaveMessage.set(null), 5000);
        },
        error: (err) => {
          this.isSavingAnthropicConfig.set(false);
          this.anthropicSaveError.set(err?.error?.detail || err?.message || 'Failed to save default model.');
        }
      });
    };

    if (saveKey$) {
      saveKey$.subscribe({ next: afterKey, error: (err) => {
        this.isSavingAnthropicConfig.set(false);
        this.anthropicSaveError.set(err?.error?.detail || err?.message || 'Failed to update Anthropic API key.');
      }});
    } else {
      afterKey();
    }
  }

  public testAnthropicConfig(): void {
    const key = this.anthropicKeyInput().trim();
    if (!key) return;
    this.isTestingAnthropicConfig.set(true);
    this.anthropicSaveError.set(null);
    this.anthropicSaveMessage.set(null);

    this.systemService.testApiKey('anthropic', key, this.anthropicBaseUrlInput().trim() || undefined).subscribe({
      next: (res) => {
        this.isTestingAnthropicConfig.set(false);
        if (res?.valid) {
          this.anthropicSaveMessage.set(res?.message || '✓ Anthropic-compatible endpoint is valid!');
        } else {
          this.anthropicSaveError.set(res?.message || 'Endpoint verification failed.');
        }
        setTimeout(() => this.anthropicSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isTestingAnthropicConfig.set(false);
        this.anthropicSaveError.set(err?.error?.detail || err?.message || 'Endpoint test failed.');
      }
    });
  }

  public toggleOpenaiKeyVisibility(): void {
    this.showOpenaiKey.update(v => !v);
  }

  public toggleAnthropicKeyVisibility(): void {
    this.showAnthropicKey.update(v => !v);
  }

  public testOcrKey(): void {
    const key = this.ocrKeyInput().trim();
    if (!key) return;
    this.isTestingOcrKey.set(true);
    this.ocrSaveError.set(null);
    this.ocrSaveMessage.set(null);

    this.systemService.testApiKey('ocr', key).subscribe({
      next: (res) => {
        this.isTestingOcrKey.set(false);
        if (res?.valid) {
          this.ocrSaveMessage.set(res?.message || '✓ Vision OCR API key is valid!');
        } else {
          this.ocrSaveError.set(res?.message || 'Vision OCR API key verification failed.');
        }
        setTimeout(() => this.ocrSaveMessage.set(null), 5000);
      },
      error: (err) => {
        this.isTestingOcrKey.set(false);
        this.ocrSaveError.set(err?.error?.detail || err?.message || 'Vision OCR API key test failed.');
      }
    });
  }

  public getProviderDisplayName(tab: string): string {
    switch (tab) {
      case 'gemini': return 'Gemini';
      case 'ocr': return 'Vision OCR';
      default: return tab;
    }
  }

  public getProviderEnvVar(tab: string): string {
    switch (tab) {
      case 'gemini': return 'GEMINI_API_KEY';
      case 'ocr': return 'GOOGLE_VISION_API_KEY';
      default: return 'API_KEY';
    }
  }

  public getProviderHint(tab: string): string {
    switch (tab) {
      case 'gemini':
        return 'For a quick start, Google Gemini provides a free API key. Artemis also supports other models (OpenAI, Claude, OpenRouter, etc.)—you can configure your own API keys directly in .env or your environment.';
      case 'ocr':
        return 'Google Cloud Vision API key for on-screen OCR text detection and UI grounding.';
      default:
        return 'Configure your API key or use environment definitions.';
    }
  }

  public skipCredentialsCheck(): void {
    this.systemService.skipCredentialsCheck();
  }

  public getApiKeyPlaceholder(tab: string): string {
    switch (tab) {
      case 'gemini': return 'Enter Gemini API Key (e.g. AIzaSy...)';
      case 'ocr': return 'Enter Vision OCR API Key (e.g. AIzaSy...)';
      default: return 'Enter API Key...';
    }
  }

  public isTabProviderActive(tab: string): boolean {
    if (tab === 'ocr') {
      return this.isOcrConfigured();
    }
    const targetProvider = tab === 'gemini' ? 'google' : tab;
    const providers = this.configuredLlmProviders();
    return providers.some(p => p.provider === targetProvider);
  }

  public refreshReadiness(): void {
    this.isRefreshingDiagnostics.set(true);
    this.systemService.fetchReadiness(false, true).subscribe({
      next: () => {
        this.systemService.fetchModelConfigEnv().subscribe({
          next: () => {
            setTimeout(() => this.isRefreshingDiagnostics.set(false), 450);
          },
          error: () => this.isRefreshingDiagnostics.set(false)
        });
      },
      error: () => this.isRefreshingDiagnostics.set(false)
    });
  }

  public restartAdbServer(): void {
    this.adbRestartFeedback.set(null);
    this.systemService.restartAdb().subscribe({
      next: (res) => {
        this.adbRestartFeedback.set(
          res?.restart_result?.skipped ? 'Devices Refreshed ✓' : 'ADB Refreshed ✓'
        );
        setTimeout(() => this.adbRestartFeedback.set(null), 2500);
      },
      error: () => {
        this.adbRestartFeedback.set('Restart Failed');
        setTimeout(() => this.adbRestartFeedback.set(null), 3000);
      }
    });
  }

  public connectWifiDevice(): void {
    if (this.isRemoteAdbServer()) {
      this.wifiConnectError.set('Switch to local ADB before connecting a Wireless ADB device.');
      return;
    }
    const host = this.wifiHost().trim();
    const portStr = this.wifiPort().trim() || '5555';
    const port = parseInt(portStr, 10) || 5555;

    if (!host) {
      this.wifiConnectError.set('Please enter a valid IP address.');
      return;
    }

    this.isConnectingWifi.set(true);
    this.wifiConnectError.set(null);
    this.wifiConnectMessage.set(null);

    this.systemService.connectWirelessAdb(host, port).subscribe({
      next: (res) => {
        this.isConnectingWifi.set(false);
        const cr = res?.connect_result;
        if (cr?.success) {
          this.wifiConnectMessage.set(`Connected to ${host}:${port}!`);
          setTimeout(() => this.wifiConnectMessage.set(null), 4000);
        } else {
          this.wifiConnectError.set(cr?.message || 'Connection failed. Please check phone IP & Wi-Fi.');
        }
      },
      error: (err) => {
        this.isConnectingWifi.set(false);
        this.wifiConnectError.set(err?.error?.detail || 'Failed to connect. Please check adb connection.');
      }
    });
  }

  public connectRemoteAdbServer(): void {
    const host = this.remoteAdbHost().trim();
    const port = Number(this.remoteAdbPort().trim());

    if (!host) {
      this.remoteAdbError.set('Enter the host name or IP address of the ADB server.');
      return;
    }
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      this.remoteAdbError.set('Enter a port between 1 and 65535.');
      return;
    }

    this.isConnectingRemoteAdb.set(true);
    this.remoteAdbError.set(null);
    this.remoteAdbMessage.set(null);
    this.remoteAdbDevices.set([]);
    this.remoteAdbProbeResult.set(null);

    this.systemService.probeAdbServer(host, port).subscribe({
      next: response => {
        this.isConnectingRemoteAdb.set(false);
        const result = response.connection_result;
        if (result.success) {
          this.remoteAdbProbeResult.set(result);
          this.remoteAdbDevices.set(result.devices || []);
          this.remoteAdbMessage.set(result.message);
        } else {
          this.remoteAdbError.set(result.message);
        }
      },
      error: error => {
        this.isConnectingRemoteAdb.set(false);
        this.remoteAdbError.set(
          error?.error?.detail || 'Unable to test the ADB server endpoint.'
        );
      }
    });
  }

  public activateRemoteAdbServer(): void {
    const tested = this.remoteAdbProbeResult();
    if (!tested?.success) {
      this.remoteAdbError.set('Test the endpoint before using it.');
      return;
    }

    this.isActivatingRemoteAdb.set(true);
    this.remoteAdbError.set(null);
    this.systemService.connectAdbServer(
      tested.endpoint.host,
      tested.endpoint.port,
      this.rememberRemoteAdb()
    ).subscribe({
      next: response => {
        this.isActivatingRemoteAdb.set(false);
        const result = response.connection_result;
        if (result.success) {
          this.remoteAdbProbeResult.set(result);
          this.remoteAdbDevices.set(result.devices || []);
          this.remoteAdbMessage.set(result.message);
        } else {
          this.remoteAdbError.set(result.message);
        }
      },
      error: error => {
        this.isActivatingRemoteAdb.set(false);
        this.remoteAdbError.set(
          error?.error?.detail || 'Unable to use the ADB server endpoint.'
        );
      }
    });
  }

  public updateRemoteAdbHost(value: string): void {
    this.remoteAdbHost.set(value);
    this.clearRemoteAdbProbe();
  }

  public updateRemoteAdbPort(value: string): void {
    this.remoteAdbPort.set(value);
    this.clearRemoteAdbProbe();
  }

  private clearRemoteAdbProbe(): void {
    this.remoteAdbProbeResult.set(null);
    this.remoteAdbDevices.set([]);
    this.remoteAdbMessage.set(null);
    this.remoteAdbError.set(null);
  }

  public switchToLocalAdbServer(): void {
    this.isSwitchingToLocalAdb.set(true);
    this.remoteAdbError.set(null);
    this.systemService.useLocalAdbServer(true).subscribe({
      next: response => {
        this.isSwitchingToLocalAdb.set(false);
        this.remoteAdbDevices.set([]);
        this.remoteAdbMessage.set(response.connection_result.message);
      },
      error: error => {
        this.isSwitchingToLocalAdb.set(false);
        this.remoteAdbError.set(
          error?.error?.detail || 'Unable to switch back to the local ADB server.'
        );
      }
    });
  }

  public toggleConnectionMethods(): void {
    this.showConnectionMethods.update(value => !value);
  }

  public launchAvdEmulator(avdName: string): void {
    if (this.isRemoteAdbServer()) {
      return;
    }
    this.systemService.launchEmulator(avdName).subscribe();
  }

  public toggleLaunchLogs(): void {
    this.showLaunchLogs.update(v => !v);
  }

  public stopEmulator(): void {
    this.systemService.stopEmulator().subscribe();
  }

  public dismissEmulatorStatus(): void {
    this.systemService.dismissEmulatorStatus().subscribe();
  }

  public selectTargetDevice(serial: string): void {
    this.systemService.selectDevice(serial).subscribe();
  }

  public getEmulatorCommand(avdName: string): string {
    const p = this.emulatorPath();
    const cmd = this.isEmulatorInPath() ? 'emulator' : (p || '~/Android/Sdk/emulator/emulator');
    return `${cmd} -avd ${avdName}`;
  }

  public copyToClipboard(text: string, id: string): void {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        this.copiedId.set(id);
        setTimeout(() => {
          if (this.copiedId() === id) {
            this.copiedId.set(null);
          }
        }, 2000);
      });
    }
  }

  public setProfile(profile: 'flash' | 'pro'): void {
    this.selectedProfile.set(profile);
  }

  public setCategory(cat: SuggestionCategory): void {
    this.selectedCategory.set(cat);
  }

  public getCategoryLabel(category: string): string {
    return category
      .split(/[_-]+/)
      .filter(Boolean)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  public shuffleSuggestions(): void {
    this.shuffleOffset.update(v => v + 3);
  }

  public getAppNamesDisplay(apps: AppReference[]): string {
    return apps.map(a => a.name).join(' + ');
  }

  public applySuggestion(item: SmartSuggestion): void {
    this.taskGoal.set(item.goal);
    this.selectedProfile.set(item.profile);
    this.errorMessage.set(null);
  }

  public applyQuickPrompt(promptGoal: string, profile?: 'flash' | 'pro'): void {
    this.taskGoal.set(promptGoal);
    if (profile) {
      this.selectedProfile.set(profile);
    }
    this.errorMessage.set(null);
  }


  public proceedToLauncher(): void {
    this.activeTab.set('launcher');
  }

  public runTask(): void {
    const goal = this.taskGoal().trim();
    if (!goal) {
      this.errorMessage.set('Please enter a task goal before running.');
      return;
    }

    if (!this.isReady()) {
      this.errorMessage.set('System prerequisites are not satisfied. Please review System Setup first.');
      this.activeTab.set('diagnostics');
      return;
    }

    this.isSubmitting.set(true);
    this.errorMessage.set(null);

    this.agentService
      .runTask(
        goal,
        this.selectedProfile(),
        this.selectedProfile() === 'pro' && this.expectedOutput().trim()
          ? this.expectedOutput().trim()
          : undefined,
        this.selectedProfile() === 'pro' ? this.enableOutputter() : undefined,
        this.selectedProfile() === 'pro'
          ? { verificationLevel: this.verificationLevel().id, explorerMode: this.explorerMode().id }
          : undefined
      )
      .subscribe({
        next: () => {
          this.isSubmitting.set(false);
          this.router.navigate(['/workspace']);
        },
        error: (err) => {
          console.error('Failed to submit task from home page:', err);
          this.isSubmitting.set(false);
          this.errorMessage.set(
            err?.error?.detail || 'Failed to submit task. Please check server connection.'
          );
        }
      });
  }
}
