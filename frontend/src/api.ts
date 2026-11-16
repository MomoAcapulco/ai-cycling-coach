import type { ActiveRoute, Activity, HistoryWeek, LoadReport, RouteSummary } from './types';
import type { AdminState, DevicesState, ProfileState, Recording, RiderProfile, Session, SessionSummary, Settings, Telemetry } from './types';

const BASE = '/api/trainer';

/** Error carrying the HTTP status and the adapter's own message when there is one. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, { cache: 'no-store', ...init });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, describeError(response.status, body));
  }
  return body as T;
}

/** The Java API wraps adapter errors as {error, adapterStatus, adapterResponse}; Python sends HTML. */
function describeError(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const { error, adapterResponse } = body as { error?: string; adapterResponse?: string };
    const detail = adapterResponse ? extractMessage(adapterResponse) : '';
    if (detail) return detail;
    if (error) return error;
  }
  return `HTTP ${status}`;
}

function extractMessage(html: string): string {
  const match = html.match(/<p>Message:\s*([^<]*)<\/p>/i);
  return (match ? match[1] : html).trim().slice(0, 300);
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  telemetry: () => request<Telemetry>('/telemetry'),
  replaySession: () => request<Session>('/replay/session'),
  replayControl: (action: string, value?: number) => request('/replay/control', json({ action, value })),
  gear: (delta: 1 | -1) => request('/gear', json({ delta })),
  grade: (gradePercent: number) =>
    request<{ targetGradePercent: number; effectiveGradePercent: number }>('/grade', json({ gradePercent })),
  adminState: () => request<AdminState>('/admin/settings'),
  saveSettings: (changes: Partial<Settings>) => request<AdminState>('/admin/settings', json(changes)),
  resetSettings: () => request<AdminState>('/admin/settings/reset', { method: 'POST' }),
  recordings: () => request<{ recordings: Recording[]; current: string | null }>('/admin/recordings'),
  uploadRecording: (file: File) =>
    request<Recording>(`/admin/recordings?name=${encodeURIComponent(file.name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: file,
    }),
  profile: () => request<ProfileState>('/admin/profile'),
  saveProfile: (profile: Partial<RiderProfile>) => request<ProfileState>('/admin/profile', json(profile)),
  sessionAction: (action: 'start' | 'pause' | 'resume' | 'finish') =>
    request<Telemetry & Partial<SessionSummary>>(`/session/${action}`, { method: 'POST' }),
  sessions: () => request<{ sessions: SessionSummary[] }>('/sessions'),
  devices: () => request<DevicesState>('/devices'),
  forgetDevice: (role: string, address?: string) =>
    request<DevicesState>(`/devices/${role}${address ? `?address=${encodeURIComponent(address)}` : ''}`, { method: 'DELETE' }),
  useDevice: (role: string, address: string) => request<DevicesState>(`/devices/${role}/use`, json({ address })),
  startRampTest: () => request<Telemetry>('/workout/ramp/start', { method: 'POST' }),
  stopWorkout: () => request<Telemetry>('/workout/stop', { method: 'POST' }),
  saveTestFtp: () => request<{ ftpWatts: number }>('/workout/ftp/save', { method: 'POST' }),
  clearWorkout: () => request<{ workout: null }>('/workout/clear', { method: 'POST' }),
  history: () => request<{ activities: Activity[]; counts: Record<string, number>; database: string }>('/history'),
  historyLoad: (days = 180) => request<LoadReport>(`/history/load?days=${days}`),
  historyWeeks: () => request<{ weeks: HistoryWeek[] }>('/history/weeks'),
  routes: () => request<{ routes: RouteSummary[]; folder: string; current: string | null; available: boolean }>('/routes'),
  uploadRoute: (file: File) =>
    request<RouteSummary>(`/routes?name=${encodeURIComponent(file.name)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/gpx+xml' }, body: file,
    }),
  route: () => request<ActiveRoute>('/route'),
  routePreview: (file: string) =>
    request<RouteSummary & { profile: { d: number; e: number; g: number }[] }>(`/routes/${encodeURIComponent(file)}`),
  startRoute: (file: string) => request<RouteSummary>('/route/start', json({ file })),
  stopRoute: () => request<{ active: false }>('/route/stop', { method: 'POST' }),
};

/** URL that downloads a finished session's file (the browser saves it). */
export const sessionFileUrl = (name: string) => `${BASE}/sessions/${encodeURIComponent(name)}`;
