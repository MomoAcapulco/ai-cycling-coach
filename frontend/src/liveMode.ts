import { api } from './api';
import type { Mode } from './types';

/**
 * The live source (real trainer or simulator) to go back to after a replay. Remembered in this browser only (a
 * convenience): without it, the real trainer.
 */
const KEY = 'aicoach.lastLiveMode';

export function rememberLiveMode(mode: string | undefined) {
  if (mode !== 'WAHOO' && mode !== 'SIMULATOR') return;
  try { window.localStorage.setItem(KEY, mode); } catch { /* private window: nothing to remember */ }
}

export function lastLiveMode(): Mode {
  try { return (window.localStorage.getItem(KEY) as Mode) || 'WAHOO'; } catch { return 'WAHOO'; }
}

export const LIVE_LABEL: Record<string, string> = { WAHOO: 'rodillo real', SIMULATOR: 'simulador' };

/** Leave the replay: back to the live source. */
export const exitReplay = () => api.saveSettings({ mode: lastLiveMode() });
